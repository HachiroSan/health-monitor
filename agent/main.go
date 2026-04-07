package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"time"
)

const heartbeatInterval = 15 * time.Second

type Report struct {
	SiteName  string    `json:"site_name"`
	SiteID    string    `json:"site_id"`
	Timestamp time.Time `json:"timestamp"`
	Status    string    `json:"status"`
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
	return Report{
		SiteName:  cfg.SiteName,
		SiteID:    cfg.SiteID,
		Timestamp: time.Now().UTC(),
		Status:    "ok",
	}
}

func sendReport(cfg Config, client *http.Client, report Report) error {
	body, err := json.Marshal(report)
	if err != nil {
		return fmt.Errorf("marshal report: %w", err)
	}

	endpoint := fmt.Sprintf("http://%s:8000/ingest", cfg.ServerIP)
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
