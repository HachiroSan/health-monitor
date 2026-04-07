from __future__ import annotations

import json
import platform
import subprocess
import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SiteTarget:
    site_name: str
    site_id: str
    router_ip: str | None = None
    pc_ip: str | None = None


def load_site_targets(path: str) -> dict[str, SiteTarget]:
    config_path = Path(path)
    if not config_path.exists():
        return {}

    data = json.loads(config_path.read_text(encoding="utf-8"))
    entries = data.get("sites", []) if isinstance(data, dict) else []

    targets: dict[str, SiteTarget] = {}
    for entry in entries:
        site_id = str(entry.get("site_id", "")).strip()
        site_name = str(entry.get("site_name", "")).strip()
        if not site_id or not site_name:
            continue

        targets[site_id] = SiteTarget(
            site_name=site_name,
            site_id=site_id,
            router_ip=_clean_optional(entry.get("router_ip")),
            pc_ip=_clean_optional(entry.get("pc_ip")),
        )

    return targets


async def probe_host(host: str | None) -> bool:
    host = _clean_optional(host)
    if not host:
        return False

    command = ["ping", "-c", "2", "-W", "4", host]
    if platform.system().lower().startswith("win"):
        command = ["ping", "-n", "2", "-w", "4000", host]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            # Increased wait_for timeout to allow multiple slow pings to complete
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=12.0)
            output_str = stdout.decode("utf-8", errors="ignore").lower()
            
            # Using "ttl=" ensures we don't falsely match "Destination host unreachable" 
            # which can sometimes return exit code 0 on Windows.
            if "ttl=" in output_str:
                return True
            return False
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            return False
    except Exception:
        return False


def _clean_optional(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
