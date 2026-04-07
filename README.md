# Health Monitor

This repository is split into two top-level parts:

- `agent/` - Go-based Windows agent that sends heartbeats
- `server/` - FastAPI-based Ubuntu jumpserver service that ingests reports, tracks site state, and sends alerts

## Current shape

- The agent is a standalone Go service with YAML config support and HTTP heartbeat reporting.
- The server is a FastAPI app with SQLite persistence, a heartbeat watchdog, and Telegram alert hooks.

## Next steps

1. Add a Windows service installer for the agent.
2. Add a systemd unit and deployment script for the server.
3. Wire in Telegram bot credentials and site configuration.
4. Keep the agent config minimal: `site_name`, `site_id`, `server_ip` (host or host:port), optional empty `auth_token`, optional `router_ip`, and optional `latest_txt_folder`.
5. If `router_ip` is set, the agent pings the router and sends router status to the server.
6. If `latest_txt_folder` is set, the agent scans for the latest `*.txt` filename by name and sends it to the server.

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

