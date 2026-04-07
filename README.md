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
4. Keep the agent config minimal: `site_name`, `site_id`, `server_ip`, and optional empty `auth_token`.
