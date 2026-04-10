# Health Monitor

This repository is split into two top-level parts:

- `agent/` - Go-based Windows agent that sends heartbeats
- `server/` - FastAPI-based Ubuntu jumpserver service that ingests reports, tracks site state, and sends alerts

## Current shape

- The agent is a standalone Go service with YAML config support and HTTP heartbeat reporting.
- The server is a FastAPI app with SQLite persistence, a heartbeat watchdog, and Telegram alert hooks.

## Build the Windows agent

From the `agent/` folder:

```powershell
go build -o agent.exe
```

Copy `config.example.yml` to `config.yml` and edit it before starting the service.

Keep the agent config minimal: `site_name`, `site_id`, `server_ip` (host or host:port), optional empty `auth_token`, and optional `latest_txt_folder`.
If `latest_txt_folder` is set, the agent scans for the latest `*.txt` filename by name and sends it to the server.

## Install `agent.exe` as a Windows service

The agent runs continuously, so the most reliable way to auto-start it after boot is to run it as a Windows service.

This example uses NSSM because the agent is a normal console binary, not a native Windows service.

1. Create a folder for the agent, for example `C:\HealthMonitor\agent`.
2. Copy `agent.exe` and `config.yml` into that folder.
3. Download NSSM and make `nssm.exe` available in your `PATH`, or run it from its extracted folder.
4. Open PowerShell as Administrator and install the service:

```powershell
nssm install HealthMonitorAgent "C:\HealthMonitor\agent\agent.exe" -config "C:\HealthMonitor\agent\config.yml"
nssm set HealthMonitorAgent AppDirectory "C:\HealthMonitor\agent"
nssm set HealthMonitorAgent Start SERVICE_AUTO_START
nssm start HealthMonitorAgent
```

`AppDirectory` matters because the agent expects to find `config.yml` relative to its working directory unless you pass an explicit `-config` path.

If you want the service to run under a specific account, set that in the Windows Services UI after installation, or create a dedicated service account and grant it access to the config file and any `latest_txt_folder` paths.

## Next steps

1. Add a systemd unit and deployment script for the server.
2. Wire in Telegram bot credentials and site configuration.
3. Add a server-side deployment guide for SQLite backup and log rotation.

## Server port

The FastAPI server reads `SERVER_HOST` and `SERVER_PORT` from `server/.env`.
If you want a custom port, set `SERVER_PORT` and run the server with:

```bash
python -m app.main
```

## Daily summary

The server can send a daily Telegram summary at a fixed local time using:

- `DAILY_SUMMARY_TIME` like `18:00`
- `DAILY_SUMMARY_TIMEZONE` like `Asia/Kuala_Lumpur`

The summary uses the configured timezone name, not a GMT offset.

## Router vs PC precedence

Router alerts take precedence over PC alerts in the daily summary because a router outage can cause the PC to appear down as well.

When the router is up but the PC is down, the alert text now calls out a possible connection issue between the router and the PC.

## Server-side checks

The jumpserver can centrally ping router and PC targets from a sites config file. Set `SITES_CONFIG_PATH` in `server/.env` to point at the JSON file that contains your site targets.

The Windows agent no longer performs router probing. It stays focused on heartbeat, latest-file tracking, and disk usage when configured.

