from __future__ import annotations

import httpx

from .settings import settings


class TelegramNotifier:
    def __init__(self) -> None:
        self._enabled = bool(settings.telegram_bot_token and settings.telegram_chat_id)

    async def send(self, message: str) -> None:
        if not self._enabled:
            return

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        payload = {"chat_id": settings.telegram_chat_id, "text": message}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
