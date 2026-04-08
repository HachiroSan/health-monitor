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
	"runtime"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

var getDiskFreeSpaceExW = syscall.NewLazyDLL("kernel32.dll").NewProc("GetDiskFreeSpaceExW")

const heartbeatInterval = 30 * time.Second

type Report struct {
	SiteName         string    `json:"site_name"`
	SiteID           string    `json:"site_id"`
	Timestamp        time.Time `json:"timestamp"`
	Status           string    `json:"status"`
	LatestFile       string    `json:"latest_file,omitempty"`
	LatestDiskUsage  string    `json:"latest_disk_usage,omitempty"`
	CpuName          string    `json:"cpu_name,omitempty"`
	CpuCores         int       `json:"cpu_cores,omitempty"`
	RamTotalMB       int64     `json:"ram_total_mb,omitempty"`
	RamAvailableMB   int64     `json:"ram_available_mb,omitempty"`
	WindowsCaption   string    `json:"windows_caption,omitempty"`
	WindowsVersion   string    `json:"windows_version,omitempty"`
	WindowsBuild     string    `json:"windows_build,omitempty"`
	GpuName          string    `json:"gpu_name,omitempty"`
	GpuDriverVersion string    `json:"gpu_driver_version,omitempty"`
	Motherboard      string    `json:"motherboard,omitempty"`
	BiosVersion      string    `json:"bios_version,omitempty"`
}

type machineTelemetry struct {
	CpuName          string `json:"cpu_name,omitempty"`
	CpuCores         int    `json:"cpu_cores,omitempty"`
	RamTotalMB       int64  `json:"ram_total_mb,omitempty"`
	RamAvailableMB   int64  `json:"ram_available_mb,omitempty"`
	WindowsCaption   string `json:"windows_caption,omitempty"`
	WindowsVersion   string `json:"windows_version,omitempty"`
	WindowsBuild     string `json:"windows_build,omitempty"`
	GpuName          string `json:"gpu_name,omitempty"`
	GpuDriverVersion string `json:"gpu_driver_version,omitempty"`
	Motherboard      string `json:"motherboard,omitempty"`
	BiosVersion      string `json:"bios_version,omitempty"`
}

func main() {
	configPath := flag.String("config", "config.yml", "path to agent config file")
	flag.Parse()

	cfg, err := LoadConfig(*configPath)
	if err != nil {
		log.Fatalf("load config: %v", err)
	}

	inventory := collectMachineTelemetry()

	client := &http.Client{Timeout: 15 * time.Second}
	ticker := time.NewTicker(heartbeatInterval)
	defer ticker.Stop()

	log.Printf("agent starting for site %s (%s)", cfg.SiteName, cfg.SiteID)
	for {
		if err := runOnce(cfg, client, inventory); err != nil {
			log.Printf("report failed: %v", err)
		}
		<-ticker.C
	}
}

func runOnce(cfg Config, client *http.Client, inventory machineTelemetry) error {
	report := buildReport(cfg, inventory)
	return sendReport(cfg, client, report)
}

func buildReport(cfg Config, inventory machineTelemetry) Report {
	latestFile := latestTxtFile(cfg.LatestFileFolder)
	latestDiskUsage := ""
	if strings.TrimSpace(cfg.LatestFileFolder) != "" {
		latestDiskUsage = diskUsageForPath(cfg.LatestFileFolder)
	}

	return Report{
		SiteName:         cfg.SiteName,
		SiteID:           cfg.SiteID,
		Timestamp:        time.Now().UTC(),
		Status:           "ok",
		LatestFile:       latestFile,
		LatestDiskUsage:  latestDiskUsage,
		CpuName:          inventory.CpuName,
		CpuCores:         inventory.CpuCores,
		RamTotalMB:       inventory.RamTotalMB,
		RamAvailableMB:   inventory.RamAvailableMB,
		WindowsCaption:   inventory.WindowsCaption,
		WindowsVersion:   inventory.WindowsVersion,
		WindowsBuild:     inventory.WindowsBuild,
		GpuName:          inventory.GpuName,
		GpuDriverVersion: inventory.GpuDriverVersion,
		Motherboard:      inventory.Motherboard,
		BiosVersion:      inventory.BiosVersion,
	}
}

func collectMachineTelemetry() machineTelemetry {
	if runtime.GOOS != "windows" {
		return machineTelemetry{}
	}

	output, err := runPowerShellTelemetryScript()
	if err != nil {
		log.Printf("machine telemetry scan failed: %v", err)
		return machineTelemetry{}
	}

	var telemetry machineTelemetry
	if err := json.Unmarshal(output, &telemetry); err != nil {
		log.Printf("machine telemetry decode failed: %v", err)
		return machineTelemetry{}
	}

	return telemetry
}

func runPowerShellTelemetryScript() ([]byte, error) {
	script := `$cpu = Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Select-Object -First 1 Name, NumberOfCores
$os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue | Select-Object -First 1 Caption, Version, BuildNumber, TotalVisibleMemorySize, FreePhysicalMemory
$gpu = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Where-Object { $_.Name } | Select-Object -First 1 Name, DriverVersion
$board = Get-CimInstance Win32_BaseBoard -ErrorAction SilentlyContinue | Select-Object -First 1 Manufacturer, Product
$bios = Get-CimInstance Win32_BIOS -ErrorAction SilentlyContinue | Select-Object -First 1 SMBIOSBIOSVersion
$motherboard = @($board.Manufacturer, $board.Product) | Where-Object { $_ } | ForEach-Object { $_.Trim() }
[pscustomobject]@{
    cpu_name = $cpu.Name
    cpu_cores = [int]$cpu.NumberOfCores
    ram_total_mb = if ($os.TotalVisibleMemorySize) { [int64][math]::Round($os.TotalVisibleMemorySize / 1024) } else { $null }
    ram_available_mb = if ($os.FreePhysicalMemory) { [int64][math]::Round($os.FreePhysicalMemory / 1024) } else { $null }
    windows_caption = $os.Caption
    windows_version = $os.Version
    windows_build = $os.BuildNumber
    gpu_name = $gpu.Name
    gpu_driver_version = $gpu.DriverVersion
    motherboard = ($motherboard -join ' ')
    bios_version = $bios.SMBIOSBIOSVersion
} | ConvertTo-Json -Compress`

	cmd := exec.Command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script)
	return cmd.Output()
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
