from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from .models import AlertItem, SiteState
from .settings import settings


def _pc_router_note(router_status: str | None, pc_status: str | None) -> str | None:
    if (router_status or "").lower() == "ok" and (pc_status or "").lower() == "down":
        return "Note: The PC is down while the router is up; this may indicate a pc crash or a connection issue between the router and the PC"
    return None


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
        
        tz = ZoneInfo(settings.daily_summary_timezone)
        timestamp = alert.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
        
        status_label = alert.status.replace("_", " ").upper()
        lines = [
            f"{emoji} {component} {status_label} | {alert.site_name}",
            f"ID: {alert.site_id}",
        ]

        if alert.checks:
            lines.append(f"Checks: {' | '.join(alert.checks)}")

        if alert.latest_file:
            lines.append(f"Latest file: {alert.latest_file}")

        if alert.latest_disk_usage:
            lines.append(f"Disk usage: {alert.latest_disk_usage}")

        if alert.component.lower() == "router" and alert.status.lower() == "down":
            lines.append("Note: The PC may also be affected, as it relies on the router for internet access")

        pc_note = _pc_router_note(alert.router_status, alert.pc_status)
        if pc_note:
            lines.append(pc_note)

        lines.append(f"Reason: {alert.message}")
        lines.append("")
        lines.append(timestamp)

        return "\n".join(lines)

    @staticmethod
    def format_daily_summary(sites: list[SiteState], generated_at: datetime, timezone_name: str) -> str:
        return TelegramNotifier._format_daily_summary(sites, generated_at, timezone_name)

    @staticmethod
    def format_daily_summary_with_alerts(
        sites: list[SiteState],
        alerts: list[AlertItem],
        generated_at: datetime,
        timezone_name: str,
    ) -> str:
        return TelegramNotifier._format_daily_summary(sites, generated_at, timezone_name)

    @staticmethod
    def _format_daily_summary(sites: list[SiteState], generated_at: datetime, timezone_name: str) -> str:
        tz = ZoneInfo(timezone_name)
        summary_time = generated_at.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
        total = len(sites)
        up_count = sum(1 for site in sites if site.status.lower() != "down")
        down_count = total - up_count

        lines = [
            f"📊 DAILY SUMMARY | {summary_time}",
            "Precedence: ROUTER > PC > SITE",
            f"Total: {total} | Up: {up_count} | Down: {down_count}",
            "",
        ]

        if not sites:
            lines.append("No site reports yet.")
            return "\n".join(lines)

        ordered_sites = sorted(sites, key=lambda item: (0 if item.status.lower() == "down" else 1, item.site_name.lower()))

        for index, site in enumerate(ordered_sites):
            emoji = "🔴" if site.status.lower() == "down" else "🟢"
            last_seen = site.last_seen.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S") if site.last_seen else "n/a"
            latest_file = site.last_report.latest_file if site.last_report and site.last_report.latest_file else ""
            latest_disk_usage = site.last_report.latest_disk_usage if site.last_report and site.last_report.latest_disk_usage else ""

            lines.extend([
                f"{emoji} {site.site_name} ({site.site_id})",
                f"Status: {site.status.replace('_', ' ').upper()}",
                f"Last seen: {last_seen}",
            ])

            lines.extend(TelegramNotifier._site_checklist_lines(site, generated_at))

            if latest_file:
                lines.append(f"Latest file: {latest_file}")

            if latest_disk_usage:
                lines.append(f"Disk usage: {latest_disk_usage}")

            if index != len(ordered_sites) - 1:
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _site_checklist_lines(site: SiteState, generated_at: datetime) -> list[str]:
        return [
            "Checklist:",
            f"- Router check: {TelegramNotifier._status_label(site.router_ip, site.router_status)}",
            f"- PC check: {TelegramNotifier._status_label(site.pc_ip, site.pc_status)}",
            f"- Heartbeat check: {TelegramNotifier._heartbeat_status(site, generated_at)}",
        ]

    @staticmethod
    def _status_label(target_ip: str | None, status: str | None) -> str:
        if not target_ip:
            return "N/A"
        if not status:
            return "N/A"
        return "DOWN" if status.lower() == "down" else "OK"

    @staticmethod
    def _heartbeat_status(site: SiteState, generated_at: datetime) -> str:
        if site.status.lower() != "down":
            return "OK"

        if site.router_status == "down" or site.pc_status == "down":
            if site.last_seen:
                age_seconds = (
                    generated_at.astimezone(timezone.utc) - site.last_seen.astimezone(timezone.utc)
                ).total_seconds()
                if age_seconds <= settings.heartbeat_timeout_seconds:
                    return "OK"
            else:
                return "DOWN"

        return "DOWN"

    @staticmethod
    def _component_label(component: str) -> str:
        component_name = component.replace("_", " ").upper()
        return component_name

    async def send(self, message: str) -> None:
        if not self._enabled:
            return

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        payload = {"chat_id": settings.telegram_chat_id, "text": message}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
