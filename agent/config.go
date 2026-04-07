package main

import (
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

type Config struct {
	SiteName         string `yaml:"site_name"`
	SiteID           string `yaml:"site_id"`
	ServerIP         string `yaml:"server_ip"`
	AuthToken        string `yaml:"auth_token"`
	LatestFileFolder string `yaml:"latest_txt_folder"`
}

func LoadConfig(path string) (Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Config{}, fmt.Errorf("read config: %w", err)
	}

	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return Config{}, fmt.Errorf("parse config: %w", err)
	}

	if cfg.SiteName == "" {
		return Config{}, fmt.Errorf("site_name is required")
	}

	if cfg.SiteID == "" {
		return Config{}, fmt.Errorf("site_id is required")
	}

	if cfg.ServerIP == "" {
		return Config{}, fmt.Errorf("server_ip is required")
	}

	return cfg, nil
}
