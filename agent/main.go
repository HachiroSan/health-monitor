package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

var getDiskFreeSpaceExW = syscall.NewLazyDLL("kernel32.dll").NewProc("GetDiskFreeSpaceExW")

const heartbeatInterval = 15 * time.Second

type Report struct {
	SiteName        string    `json:"site_name"`
	SiteID          string    `json:"site_id"`
	Timestamp       time.Time `json:"timestamp"`
	Status          string    `json:"status"`
	RouterIP        string    `json:"router_ip,omitempty"`
	RouterStatus    string    `json:"router_status,omitempty"`
	LatestFile      string    `json:"latest_file,omitempty"`
	LatestDiskUsage string    `json:"latest_disk_usage,omitempty"`
}

func main() {
	configPath := flag.String("config", "config.yml", "path to agent config file")
	flag.Parse()

	cfg, err := LoadConfig(*configPath)
	if err != nil {
		log.Fatalf("load config: %v", err)
	}

	client := &http.Client{Timeout: 15 * time.Second}
	ticker := time.NewTicker(heartbeatInterval)
	defer ticker.Stop()

	log.Printf("agent starting for site %s (%s)", cfg.SiteName, cfg.SiteID)
	for {
		if err := runOnce(cfg, client); err != nil {
			log.Printf("report failed: %v", err)
		}
		<-ticker.C
	}
}

func runOnce(cfg Config, client *http.Client) error {
	report := buildReport(cfg)
	return sendReport(cfg, client, report)
}

func buildReport(cfg Config) Report {
	latestFile := latestTxtFile(cfg.LatestFileFolder)
	latestDiskUsage := ""
	if strings.TrimSpace(cfg.LatestFileFolder) != "" {
		latestDiskUsage = diskUsageForPath(cfg.LatestFileFolder)
	}
	routerStatus := ""
	if strings.TrimSpace(cfg.RouterIP) != "" {
		if pingHost(cfg.RouterIP) {
			routerStatus = "ok"
		} else {
			routerStatus = "down"
		}
	}

	status := "ok"
	if routerStatus == "down" {
		status = "down"
	}

	return Report{
		SiteName:        cfg.SiteName,
		SiteID:          cfg.SiteID,
		Timestamp:       time.Now().UTC(),
		Status:          status,
		RouterIP:        strings.TrimSpace(cfg.RouterIP),
		RouterStatus: routerStatus,
		LatestFile:      latestFile,
		LatestDiskUsage: latestDiskUsage,
	}
}

func pingHost(host string) bool {
	host = strings.TrimSpace(host)
	if host == "" {
		return false
	}

	cmd := exec.Command("ping", "-n", "1", "-w", "1000", host)
	if err := cmd.Run(); err != nil {
		return false
	}

	return true
}

func latestTxtFile(folder string) string {
	folder = strings.TrimSpace(folder)
	if folder == "" {
		return ""
	}

	entries, err := os.ReadDir(folder)
	if err != nil {
		log.Printf("latest txt scan failed for %q: %v", folder, err)
		return ""
	}

	files := make([]string, 0)
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}

		name := entry.Name()
		if strings.EqualFold(filepath.Ext(name), ".txt") {
			files = append(files, name)
		}
	}

	if len(files) == 0 {
		return ""
	}

	sort.Strings(files)
	return files[len(files)-1]
}

func diskUsageForPath(path string) string {
	path = strings.TrimSpace(path)
	if path == "" {
		return ""
	}

	absPath, err := filepath.Abs(path)
	if err == nil {
		path = absPath
	}

	utf16Path, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return ""
	}

	var freeBytesAvailable uint64
	var totalBytes uint64
	var totalFreeBytes uint64
	r1, _, callErr := getDiskFreeSpaceExW.Call(
		uintptr(unsafe.Pointer(utf16Path)),
		uintptr(unsafe.Pointer(&freeBytesAvailable)),
		uintptr(unsafe.Pointer(&totalBytes)),
		uintptr(unsafe.Pointer(&totalFreeBytes)),
	)
	if r1 == 0 {
		log.Printf("disk usage scan failed for %q: %v", path, callErr)
		return ""
	}

	if totalBytes == 0 {
		return ""
	}

	usedBytes := totalBytes - totalFreeBytes
	usedPercent := int(float64(usedBytes) * 100 / float64(totalBytes))
	return fmt.Sprintf("%d%% used (%s free of %s)", usedPercent, formatBytes(totalFreeBytes), formatBytes(totalBytes))
}

func formatBytes(value uint64) string {
	units := []string{"B", "KB", "MB", "GB", "TB"}
	amount := float64(value)
	unitIndex := 0
	for amount >= 1024 && unitIndex < len(units)-1 {
		amount /= 1024
		unitIndex++
	}

	if unitIndex == 0 {
		return strconv.FormatUint(value, 10) + " " + units[unitIndex]
	}

	return fmt.Sprintf("%.1f %s", amount, units[unitIndex])
}

func sendReport(cfg Config, client *http.Client, report Report) error {
	body, err := json.Marshal(report)
	if err != nil {
		return fmt.Errorf("marshal report: %w", err)
	}

	endpoint := fmt.Sprintf("http://%s/ingest", strings.TrimSpace(cfg.ServerIP))
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if cfg.AuthToken != "" {
		req.Header.Set("Authorization", "Bearer "+cfg.AuthToken)
	}

	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("post report: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 300 {
		return fmt.Errorf("server responded with %s", resp.Status)
	}

	return nil
}
