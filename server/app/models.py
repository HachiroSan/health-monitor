from datetime import datetime

from pydantic import BaseModel, Field


class AgentReport(BaseModel):
    site_name: str
    site_id: str
    timestamp: datetime
    status: str = Field(default="ok")


class SiteState(BaseModel):
    site_name: str
    site_id: str
    status: str
    last_seen: datetime | None = None
    last_report: AgentReport | None = None


class AlertItem(BaseModel):
    site_name: str
    site_id: str
    component: str = Field(default="site")
    status: str
    message: str
    checks: list[str] = Field(default_factory=list)
    created_at: datetime
