from __future__ import annotations

from datetime import timezone

import httpx

from .models import AlertItem
from .settings import settings


class TelegramNotifier:
    def __init__(self) -> None:
        self._enabled = bool(settings.telegram_bot_token and settings.telegram_chat_id)

    @staticmethod
    def format_alert(alert: AlertItem) -> str:
        emoji_map = {
            "down": "🔴",
            "recovered": "🟢",
            "warning": "🟡",
        }
        emoji = emoji_map.get(alert.status.lower(), "ℹ️")
        component = alert.component.replace("_", " ").upper()
        timestamp = alert.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        status_label = alert.status.replace("_", " ").upper()
        lines = [
            f"{emoji} {component} {status_label} | {alert.site_name}",
            f"ID: {alert.site_id}",
        ]

        if alert.checks:
            lines.append(f"Checks: {' | '.join(alert.checks)}")

        lines.append(f"Reason: {alert.message}")
        lines.append("")
        lines.append(timestamp)

        return "\n".join(lines)

    async def send(self, message: str) -> None:
        if not self._enabled:
            return

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        payload = {"chat_id": settings.telegram_chat_id, "text": message}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
