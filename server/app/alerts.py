from __future__ import annotations

from datetime import datetime, timezone
from collections import defaultdict

import httpx

from .models import AlertItem, SiteState
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

        if alert.latest_file:
            lines.append(f"Latest file: {alert.latest_file}")

        if alert.latest_disk_usage:
            lines.append(f"Disk usage: {alert.latest_disk_usage}")

        if alert.component.lower() == "router" and alert.status.lower() == "down":
            lines.append("Note: The PC may also be affected, as it relies on the router for internet access")

        lines.append(f"Reason: {alert.message}")
        lines.append("")
        lines.append(timestamp)

        return "\n".join(lines)

    @staticmethod
    def format_daily_summary(sites: list[SiteState], generated_at: datetime, timezone_name: str) -> str:
        summary_time = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        total = len(sites)
        up_count = sum(1 for site in sites if site.status.lower() != "down")
        down_count = total - up_count

        lines = [
            f"📊 DAILY SUMMARY | {summary_time} | {timezone_name}",
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
            last_seen = site.last_seen.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if site.last_seen else "n/a"
            latest_file = site.last_report.latest_file if site.last_report and site.last_report.latest_file else ""
            latest_disk_usage = site.last_report.latest_disk_usage if site.last_report and site.last_report.latest_disk_usage else ""
            status_label = site.status.replace("_", " ").upper()
            site_alerts = []
            lines.extend(
                [
                    f"{emoji} {site.site_name} ({site.site_id})",
                    f"Status: {status_label}",
                    f"Last seen: {last_seen}",
                ]
            )

            if latest_file:
                lines.append(f"Latest file: {latest_file}")

            if latest_disk_usage:
                lines.append(f"Disk usage: {latest_disk_usage}")

            if index != len(ordered_sites) - 1:
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_daily_summary_with_alerts(
        sites: list[SiteState],
        alerts: list[AlertItem],
        generated_at: datetime,
        timezone_name: str,
    ) -> str:
        summary_time = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        total = len(sites)
        up_count = sum(1 for site in sites if site.status.lower() != "down")
        down_count = total - up_count

        alerts_by_site: dict[str, list[AlertItem]] = defaultdict(list)
        for alert in alerts:
            alerts_by_site[alert.site_id].append(alert)

        lines = [
            f"📊 DAILY SUMMARY | {summary_time} | {timezone_name}",
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
            last_seen = site.last_seen.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if site.last_seen else "n/a"
            latest_file = site.last_report.latest_file if site.last_report and site.last_report.latest_file else ""
            latest_disk_usage = site.last_report.latest_disk_usage if site.last_report and site.last_report.latest_disk_usage else ""
            site_alerts = alerts_by_site.get(site.site_id, [])

            primary_alert = TelegramNotifier._pick_primary_component_alert(site_alerts)
            related_components = TelegramNotifier._related_components(site_alerts, primary_alert.component if primary_alert else None)

            lines.extend([
                f"{emoji} {site.site_name} ({site.site_id})",
                f"Overall: {site.status.replace('_', ' ').upper()}",
            ])

            if primary_alert is not None:
                lines.append(f"Primary: {TelegramNotifier._component_label(primary_alert.component)} {primary_alert.status.replace('_', ' ').upper()}")

                if primary_alert.component.lower() == "router" and primary_alert.status.lower() == "down":
                    lines.append("Note: The PC may also be affected, as it relies on the router for internet access")

            if related_components:
                lines.append(f"Related: {', '.join(f'{component} DOWN' for component in related_components)}")

            if any(alert.component.lower() == "router" and alert.status.lower() == "down" for alert in site_alerts):
                lines.append("Priority: Router outage affects PC connectivity")

            lines.append(f"Last seen: {last_seen}")

            if latest_file:
                lines.append(f"Latest file: {latest_file}")

            if latest_disk_usage:
                lines.append(f"Disk usage: {latest_disk_usage}")

            if index != len(ordered_sites) - 1:
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _component_label(component: str) -> str:
        component_name = component.replace("_", " ").upper()
        return component_name

    @staticmethod
    def _pick_primary_component_alert(alerts: list[AlertItem]) -> AlertItem | None:
        if not alerts:
            return None

        component_order = {"router": 0, "pc": 1, "site": 2}
        down_alerts = [alert for alert in alerts if alert.status.lower() == "down"]
        if not down_alerts:
            return None

        return sorted(
            down_alerts,
            key=lambda alert: (component_order.get(alert.component.lower(), 99), -alert.created_at.timestamp()),
        )[0]

    @staticmethod
    def _related_components(alerts: list[AlertItem], primary_component: str | None = None) -> list[str]:
        component_order = {"router": 0, "pc": 1, "site": 2}
        down_components = {
            alert.component.lower()
            for alert in alerts
            if alert.status.lower() == "down"
        }
        if primary_component:
            down_components.discard(primary_component.lower())
        ordered = sorted(down_components, key=lambda component: component_order.get(component, 99))
        return [TelegramNotifier._component_label(component) for component in ordered]

    async def send(self, message: str) -> None:
        if not self._enabled:
            return

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        payload = {"chat_id": settings.telegram_chat_id, "text": message}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
