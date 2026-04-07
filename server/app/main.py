from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI
import uvicorn

from .alerts import TelegramNotifier
from .db import fetch_alerts_since, initialize_database, store_alert, store_report
from .models import AgentReport, AlertItem, SiteState
from .settings import settings


@dataclass
class RuntimeState:
    sites: dict[str, SiteState]
    notifier: TelegramNotifier
    summary_sent_date: date | None


runtime = RuntimeState(sites={}, notifier=TelegramNotifier(), summary_sent_date=None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_database(settings.database_path)
    watchdog = asyncio.create_task(watchdog_loop())
    summary = asyncio.create_task(daily_summary_loop())
    try:
        yield
    finally:
        watchdog.cancel()
        summary.cancel()
        try:
            await watchdog
        except asyncio.CancelledError:
            pass
        try:
            await summary
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Health Monitor Server", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest")
async def ingest(report: AgentReport) -> dict[str, str]:
    await store_report(settings.database_path, report)

    previous = runtime.sites.get(report.site_id)

    if previous is None:
        await raise_alert(
            report.site_name,
            report.site_id,
            "site",
            "started",
            "agent started reporting",
            latest_file=report.latest_file,
        )

    runtime.sites[report.site_id] = SiteState(
        site_name=report.site_name,
        site_id=report.site_id,
        status=report.status,
        last_seen=report.timestamp,
        last_report=report,
    )

    previous_router_status = previous.last_report.router_status if previous and previous.last_report else None
    if report.router_status and report.router_status != previous_router_status:
        router_status = report.router_status.lower()
        if router_status == "down":
            await raise_alert(
                report.site_name,
                report.site_id,
                "router",
                "down",
                f"router unreachable: {report.router_ip or 'unknown'}",
                latest_file=report.latest_file,
            )
        elif previous_router_status == "down" and router_status == "ok":
            await raise_alert(
                report.site_name,
                report.site_id,
                "router",
                "recovered",
                f"router reachable again: {report.router_ip or 'unknown'}",
                latest_file=report.latest_file,
            )

    if previous and previous.status == "down" and report.status != "down":
        await raise_alert(
            report.site_name,
            report.site_id,
            "site",
            "recovered",
            "site reported back online",
            latest_file=report.latest_file,
            latest_disk_usage=report.latest_disk_usage,
        )

    return {"status": "accepted"}


@app.get("/sites")
async def sites() -> list[SiteState]:
    return list(runtime.sites.values())


@app.get("/alerts")
async def alerts() -> dict[str, str]:
    return {"status": "not_implemented_yet"}


async def watchdog_loop() -> None:
    while True:
        now = datetime.now(timezone.utc)
        for site_id, site in list(runtime.sites.items()):
            if site.last_seen is None:
                continue

            age = (now - site.last_seen).total_seconds()
            if age > settings.heartbeat_timeout_seconds and site.status != "down":
                runtime.sites[site_id] = SiteState(
                    site_name=site.site_name,
                    site_id=site_id,
                    status="down",
                    last_seen=site.last_seen,
                    last_report=site.last_report,
                )
                await raise_alert(
                    site.site_name,
                    site_id,
                    "site",
                    "down",
                    f"site has not reported for {int(age)} seconds",
                    latest_file=site.last_report.latest_file if site.last_report else None,
                    latest_disk_usage=site.last_report.latest_disk_usage if site.last_report else None,
                )

        await asyncio.sleep(settings.heartbeat_poll_seconds)


async def daily_summary_loop() -> None:
    summary_time = parse_daily_summary_time(settings.daily_summary_time)
    summary_tz = load_summary_timezone()

    while True:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(summary_tz)
        target_local = now_local.replace(
            hour=summary_time.hour,
            minute=summary_time.minute,
            second=0,
            microsecond=0,
        )

        if now_local >= target_local:
            target_local = target_local + timedelta(days=1)

        sleep_seconds = max(1, int((target_local.astimezone(timezone.utc) - now_utc).total_seconds()))
        await asyncio.sleep(sleep_seconds)

        current_date = datetime.now(summary_tz).date()
        if runtime.summary_sent_date == current_date:
            continue

        await send_daily_summary()
        runtime.summary_sent_date = current_date


async def send_daily_summary() -> None:
    summary_tz = summary_timezone()
    now = datetime.now(summary_tz)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    alerts = await fetch_alerts_since(settings.database_path, start_of_day.astimezone(timezone.utc))
    summary = TelegramNotifier.format_daily_summary_with_alerts(
        list(runtime.sites.values()),
        alerts,
        now,
        settings.daily_summary_timezone,
    )
    try:
        await runtime.notifier.send(summary)
    except Exception:
        pass


def parse_daily_summary_time(value: str) -> dt_time:
    hour_str, minute_str = value.split(":", maxsplit=1)
    return dt_time(hour=int(hour_str), minute=int(minute_str))


def load_summary_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.daily_summary_timezone)
    except Exception:
        return ZoneInfo("UTC")


def summary_timezone() -> ZoneInfo:
    return load_summary_timezone()


async def raise_alert(
    site_name: str,
    site_id: str,
    component: str,
    status: str,
    message: str,
    checks: list[str] | None = None,
    latest_file: str | None = None,
    latest_disk_usage: str | None = None,
) -> None:
    alert = AlertItem(
        site_name=site_name,
        site_id=site_id,
        component=component,
        status=status,
        message=message,
        checks=checks or [],
        latest_file=latest_file,
        latest_disk_usage=latest_disk_usage,
        created_at=datetime.now(timezone.utc),
    )
    await store_alert(settings.database_path, alert)

    try:
        await runtime.notifier.send(TelegramNotifier.format_alert(alert))
    except Exception:
        pass


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
