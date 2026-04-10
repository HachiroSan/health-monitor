from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI
import uvicorn

from .alerts import TelegramNotifier
from .db import fetch_alerts_since, initialize_database, store_alert, store_report
from .models import AgentReport, AlertItem, SiteState
from .site_targets import SiteTarget, load_site_targets, probe_host
from .settings import settings

logging.basicConfig(
    level=logging.DEBUG if settings.debug_logging else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("health_monitor")

@dataclass
class RuntimeState:
    sites: dict[str, SiteState]
    targets: dict[str, SiteTarget]
    notifier: TelegramNotifier
    summary_sent_date: date | None


runtime = RuntimeState(sites={}, targets={}, notifier=TelegramNotifier(), summary_sent_date=None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_database(settings.database_path)
    runtime.targets = load_site_targets(settings.sites_config_path)
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


def compute_overall_status(last_seen: datetime | None) -> str:
    if last_seen is None:
        return "down"
    age_seconds = (datetime.now(timezone.utc) - last_seen).total_seconds()
    if age_seconds > settings.heartbeat_timeout_seconds:
        return "down"
    return "ok"


@app.post("/ingest")
async def ingest(report: AgentReport) -> dict[str, str]:
    await store_report(settings.database_path, report)

    previous = runtime.sites.get(report.site_id)
    target = runtime.targets.get(report.site_id)
    router_status = "ok"
    pc_status = "ok"

    # Compute new overall status using report.timestamp as the fresh last_seen
    new_status = compute_overall_status(report.timestamp)
    
    is_first_report = previous is None or previous.last_seen is None
    recovered_now = bool(not is_first_report and previous.status == "down" and new_status == "ok")

    if is_first_report:
        logger.info("Agent started reporting for site %s for the first time", report.site_id)
        await raise_alert(
            report.site_name,
            report.site_id,
            "site",
            "started",
            "agent started reporting",
            latest_file=report.latest_file,
            latest_disk_usage=report.latest_disk_usage,
        )

    runtime.sites[report.site_id] = SiteState(
        site_name=report.site_name,
        site_id=report.site_id,
        status=new_status,
        router_ip=target.router_ip if target else (previous.router_ip if previous else None),
        pc_ip=target.pc_ip if target else (previous.pc_ip if previous else None),
        router_status=router_status,
        pc_status=pc_status,
        last_probe_at=previous.last_probe_at if previous else None,
        last_seen=report.timestamp,
        last_report=report,
    )

    if recovered_now:
        logger.info("Site %s recovered via ingest heartbeat (status changed from down to ok)", report.site_id)
        if previous and previous.router_status == "down":
             logger.info("Router recovered for site %s via heartbeat", report.site_id)
             await raise_alert(
                 report.site_name,
                 report.site_id,
                 "router",
                 "recovered",
                 f"router reachable again (via heartbeat)"
             )
        if previous and previous.pc_status == "down":
             logger.info("PC recovered for site %s via heartbeat", report.site_id)
             await raise_alert(
                 report.site_name,
                 report.site_id,
                 "pc",
                 "recovered",
                 f"pc reachable again (via heartbeat)"
             )

        await raise_alert(
            report.site_name,
            report.site_id,
            "site",
            "recovered",
            "agent reported back online",
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
                logger.warning("Watchdog triggered site down for %s: missing for %.1fs", site_id, age)
                
                target = runtime.targets.get(site_id)
                router_ip = target.router_ip if target else site.router_ip
                pc_ip = target.pc_ip if target else site.pc_ip
                
                router_status = "unknown"
                pc_status = "unknown"
                
                if router_ip:
                    router_up = await probe_host(router_ip)
                    router_status = "ok" if router_up else "down"
                    
                    if router_up and pc_ip:
                        pc_up = await probe_host(pc_ip)
                        pc_status = "ok" if pc_up else "down"
                
                runtime.sites[site_id] = SiteState(
                    site_name=site.site_name,
                    site_id=site_id,
                    status="down",
                    last_seen=site.last_seen,
                    last_report=site.last_report,
                    router_ip=router_ip,
                    pc_ip=pc_ip,
                    router_status=router_status,
                    pc_status=pc_status,
                    last_probe_at=now,
                )
                
                await raise_alert(
                    site.site_name,
                    site_id,
                    "site",
                    "down",
                    f"agent has not reported for {int(age)} seconds",
                    latest_file=site.last_report.latest_file if site.last_report else None,
                    latest_disk_usage=site.last_report.latest_disk_usage if site.last_report else None,
                )
                
                if router_status == "down":
                    logger.warning("Router down for site %s: %s", site_id, router_ip)
                    await raise_alert(
                        site.site_name,
                        site_id,
                        "router",
                        "down",
                        f"router unreachable: {router_ip or 'unknown'}",
                    )
                
                if pc_status == "down":
                    logger.warning("PC down for site %s: %s", site_id, pc_ip)
                    await raise_alert(
                        site.site_name,
                        site_id,
                        "pc",
                        "down",
                        f"pc unreachable: {pc_ip}",
                        router_status=router_status,
                        pc_status=pc_status,
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
        logger.info("Sent daily summary")
    except Exception as e:
        logger.error("Failed to send daily summary: %s", e)


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
    router_status: str | None = None,
    pc_status: str | None = None,
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
        router_status=router_status,
        pc_status=pc_status,
        created_at=datetime.now(timezone.utc),
    )
    await store_alert(settings.database_path, alert)

    try:
        await runtime.notifier.send(TelegramNotifier.format_alert(alert))
    except Exception as e:
        logger.error("Failed to send Telegram alert for %s: %s", site_id, e)


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
