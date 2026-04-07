from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import FastAPI
import uvicorn

from .alerts import TelegramNotifier
from .db import initialize_database, store_alert, store_report
from .models import AgentReport, AlertItem, SiteState
from .settings import settings


@dataclass
class RuntimeState:
    sites: dict[str, SiteState]
    notifier: TelegramNotifier


runtime = RuntimeState(sites={}, notifier=TelegramNotifier())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_database(settings.database_path)
    watchdog = asyncio.create_task(watchdog_loop())
    try:
        yield
    finally:
        watchdog.cancel()
        try:
            await watchdog
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
    runtime.sites[report.site_id] = SiteState(
        site_name=report.site_name,
        site_id=report.site_id,
        status=report.status,
        last_seen=report.timestamp,
        last_report=report,
    )

    if previous and previous.status == "down" and report.status != "down":
        await raise_alert(report.site_name, report.site_id, "site", "recovered", "site reported back online")

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
                )

        await asyncio.sleep(settings.heartbeat_poll_seconds)


async def raise_alert(
    site_name: str,
    site_id: str,
    component: str,
    status: str,
    message: str,
    checks: list[str] | None = None,
) -> None:
    alert = AlertItem(
        site_name=site_name,
        site_id=site_id,
        component=component,
        status=status,
        message=message,
        checks=checks or [],
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
