from __future__ import annotations

import aiosqlite

from .models import AgentReport, AlertItem


SCHEMA = """
CREATE TABLE IF NOT EXISTS site_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    site_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    site_id TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


async def initialize_database(database_path: str) -> None:
    async with aiosqlite.connect(database_path) as connection:
        await connection.executescript(SCHEMA)
        await connection.commit()


async def store_report(database_path: str, report: AgentReport) -> None:
    async with aiosqlite.connect(database_path) as connection:
        await connection.execute(
            "INSERT INTO site_reports (site_name, site_id, timestamp, status, payload) VALUES (?, ?, ?, ?, ?)",
            (report.site_name, report.site_id, report.timestamp.isoformat(), report.status, report.model_dump_json()),
        )
        await connection.commit()


async def store_alert(database_path: str, alert: AlertItem) -> None:
    async with aiosqlite.connect(database_path) as connection:
        await connection.execute(
            "INSERT INTO alerts (site_name, site_id, status, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (alert.site_name, alert.site_id, alert.status, alert.message, alert.created_at.isoformat()),
        )
        await connection.commit()
