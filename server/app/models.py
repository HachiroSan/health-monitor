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
    status: str
    message: str
    created_at: datetime
