from datetime import datetime

from pydantic import BaseModel, Field


class AgentReport(BaseModel):
    site_name: str
    site_id: str
    timestamp: datetime
    status: str = Field(default="ok")
    router_ip: str | None = None
    router_status: str | None = None
    latest_file: str | None = None
    latest_disk_usage: str | None = None
    cpu_name: str | None = None
    cpu_cores: int | None = None
    ram_total_mb: int | None = None
    ram_available_mb: int | None = None
    windows_caption: str | None = None
    windows_version: str | None = None
    windows_build: str | None = None
    gpu_name: str | None = None
    gpu_driver_version: str | None = None
    motherboard: str | None = None
    bios_version: str | None = None


class SiteState(BaseModel):
    site_name: str
    site_id: str
    status: str
    router_ip: str | None = None
    pc_ip: str | None = None
    router_status: str | None = None
    pc_status: str | None = None
    last_probe_at: datetime | None = None
    last_seen: datetime | None = None
    last_report: AgentReport | None = None


class AlertItem(BaseModel):
    site_name: str
    site_id: str
    component: str = Field(default="site")
    status: str
    message: str
    checks: list[str] = Field(default_factory=list)
    latest_file: str | None = None
    latest_disk_usage: str | None = None
    created_at: datetime
