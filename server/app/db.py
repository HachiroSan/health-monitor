from __future__ import annotations

import json
from datetime import datetime

import aiosqlite

from .models import AgentReport, AlertItem


SCHEMA = """
CREATE TABLE IF NOT EXISTS site_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    site_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL,
    latest_file TEXT NOT NULL DEFAULT '',
    latest_disk_usage TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    site_id TEXT NOT NULL,
    component TEXT NOT NULL DEFAULT 'site',
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    checks TEXT NOT NULL DEFAULT '[]',
    latest_file TEXT NOT NULL DEFAULT '',
    latest_disk_usage TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


async def initialize_database(database_path: str) -> None:
    async with aiosqlite.connect(database_path) as connection:
        await connection.executescript(SCHEMA)

        async with connection.execute("PRAGMA table_info(alerts)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}

        if "component" not in columns:
            await connection.execute("ALTER TABLE alerts ADD COLUMN component TEXT NOT NULL DEFAULT 'site'")

        if "checks" not in columns:
            await connection.execute("ALTER TABLE alerts ADD COLUMN checks TEXT NOT NULL DEFAULT '[]'")

        if "latest_file" not in columns:
            await connection.execute("ALTER TABLE alerts ADD COLUMN latest_file TEXT NOT NULL DEFAULT ''")

        if "latest_disk_usage" not in columns:
            await connection.execute("ALTER TABLE alerts ADD COLUMN latest_disk_usage TEXT NOT NULL DEFAULT ''")

        async with connection.execute("PRAGMA table_info(site_reports)") as cursor:
            report_columns = {row[1] for row in await cursor.fetchall()}

        if "latest_file" not in report_columns:
            await connection.execute("ALTER TABLE site_reports ADD COLUMN latest_file TEXT NOT NULL DEFAULT ''")

        if "latest_disk_usage" not in report_columns:
            await connection.execute("ALTER TABLE site_reports ADD COLUMN latest_disk_usage TEXT NOT NULL DEFAULT ''")

        await connection.commit()


async def store_report(database_path: str, report: AgentReport) -> None:
    async with aiosqlite.connect(database_path) as connection:
        await connection.execute(
            "INSERT INTO site_reports (site_name, site_id, timestamp, status, latest_file, latest_disk_usage, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                report.site_name,
                report.site_id,
                report.timestamp.isoformat(),
                report.status,
                report.latest_file or "",
                report.latest_disk_usage or "",
                report.model_dump_json(),
            ),
        )
        await connection.commit()


async def store_alert(database_path: str, alert: AlertItem) -> None:
    async with aiosqlite.connect(database_path) as connection:
        await connection.execute(
            "INSERT INTO alerts (site_name, site_id, component, status, message, checks, latest_file, latest_disk_usage, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                alert.site_name,
                alert.site_id,
                alert.component,
                alert.status,
                alert.message,
                json.dumps(alert.checks),
                alert.latest_file or "",
                alert.latest_disk_usage or "",
                alert.created_at.isoformat(),
            ),
        )
        await connection.commit()


async def fetch_alerts_since(database_path: str, since: datetime) -> list[AlertItem]:
    async with aiosqlite.connect(database_path) as connection:
        connection.row_factory = aiosqlite.Row
        async with connection.execute(
            """
            SELECT site_name, site_id, component, status, message, checks, latest_file, created_at
            FROM alerts
            WHERE created_at >= ?
            ORDER BY created_at ASC, id ASC
            """,
            (since.isoformat(),),
        ) as cursor:
            rows = await cursor.fetchall()

    alerts: list[AlertItem] = []
    for row in rows:
        alerts.append(
            AlertItem(
                site_name=row["site_name"],
                site_id=row["site_id"],
                component=row["component"],
                status=row["status"],
                message=row["message"],
                checks=json.loads(row["checks"] or "[]"),
                latest_file=row["latest_file"] or None,
                created_at=datetime.fromisoformat(row["created_at"]),
            )
        )

    return alerts
