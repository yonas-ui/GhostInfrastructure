from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

ServiceType = Literal["application", "api", "database", "cache", "queue", "storage", "worker", "external", "other"]
Status = Literal["healthy", "degraded", "down", "unknown"]
CheckStatus = Literal["healthy", "degraded", "down"]
DepKind = Literal["http", "grpc", "database", "queue", "cache", "event", "batch", "dns", "other"]
Severity = Literal["low", "medium", "high", "critical"]
IncidentStatus = Literal["investigating", "identified", "monitoring", "resolved"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth
class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORM):
    id: int
    email: str
    name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut | None = None


# ------------------------------------------------------------ projects
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""


class ProjectOut(ORM):
    id: int
    name: str
    description: str
    created_at: datetime


# ------------------------------------------------------------ services
class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: ServiceType = "application"
    description: str = ""
    owner: str = ""
    environment: str = "production"
    criticality: int = Field(3, ge=1, le=5)
    health_url: str | None = None
    tags: list[str] = []


class ServiceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    type: ServiceType | None = None
    description: str | None = None
    owner: str | None = None
    environment: str | None = None
    criticality: int | None = Field(None, ge=1, le=5)
    health_url: str | None = None
    tags: list[str] | None = None


class ServiceOut(ORM):
    id: int
    project_id: int
    name: str
    type: str
    description: str
    owner: str
    environment: str
    criticality: int
    status: str
    health_url: str | None
    tags: list[str]
    last_checked_at: datetime | None
    created_at: datetime


# -------------------------------------------------------- dependencies
class DependencyCreate(BaseModel):
    source_id: int  # the service that depends ...
    target_id: int  # ... on this one
    kind: DepKind = "http"
    description: str = ""
    documented: bool = True


class DependencyUpdate(BaseModel):
    kind: DepKind | None = None
    description: str | None = None
    documented: bool | None = None


class DependencyOut(ORM):
    id: int
    project_id: int
    source_id: int
    target_id: int
    kind: str
    description: str
    documented: bool
    discovered_by: str
    observed_count: int
    last_seen_at: datetime | None


# -------------------------------------------------------------- health
class HealthReport(BaseModel):
    status: CheckStatus
    latency_ms: float | None = None
    status_code: int | None = None
    error: str | None = None


class HealthCheckOut(ORM):
    id: int
    service_id: int
    status: str
    latency_ms: float | None
    status_code: int | None
    error: str | None
    source: str
    checked_at: datetime


# ----------------------------------------------------------- incidents
class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    severity: Severity = "medium"
    root_cause_service_id: int | None = None
    summary: str = ""


class IncidentUpdate(BaseModel):
    title: str | None = None
    severity: Severity | None = None
    status: IncidentStatus | None = None
    root_cause_service_id: int | None = None
    summary: str | None = None


class IncidentEventCreate(BaseModel):
    message: str = Field(min_length=1)
    service_id: int | None = None
    event_type: Literal["note", "status_change", "deployment", "impact"] = "note"


class IncidentEventOut(ORM):
    id: int
    incident_id: int
    service_id: int | None
    event_type: str
    message: str
    created_at: datetime


class IncidentOut(ORM):
    id: int
    project_id: int
    title: str
    severity: str
    status: str
    root_cause_service_id: int | None
    auto_detected: bool
    summary: str
    started_at: datetime
    resolved_at: datetime | None


class IncidentDetail(IncidentOut):
    events: list[IncidentEventOut] = []


# --------------------------------------------------------- deployments
class DeploymentCreate(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    deployed_by: str = ""
    status: Literal["success", "failed", "rolled_back"] = "success"
    notes: str = ""
    deployed_at: datetime | None = None


class DeploymentOut(ORM):
    id: int
    project_id: int
    service_id: int
    version: str
    deployed_by: str
    status: str
    notes: str
    deployed_at: datetime


# --------------------------------------------------------- simulations
class SimulationCreate(BaseModel):
    failed_service_ids: list[int] = Field(min_length=1)
    name: str = ""


class SimulationOut(ORM):
    id: int
    project_id: int
    name: str
    failed_service_ids: list[int]
    result: dict[str, Any]
    created_at: datetime


# -------------------------------------------------------------- alerts
class AlertOut(ORM):
    id: int
    project_id: int
    service_id: int | None
    incident_id: int | None
    kind: str
    level: str
    message: str
    acknowledged: bool
    created_at: datetime


# ----------------------------------------------------------- discovery
class Observation(BaseModel):
    source: str
    target: str
    kind: DepKind = "http"


class ObservationBatch(BaseModel):
    observations: list[Observation] = Field(min_length=1)
    create_missing_services: bool = True


class ComposeImport(BaseModel):
    content: str = Field(min_length=1)
