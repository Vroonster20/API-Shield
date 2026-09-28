"""Strict shared configuration and API contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


ConfigId = Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Name = Annotated[StrictStr, Field(min_length=1, max_length=80)]
Millis = StrictInt
SupportedMethod = Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class RateLimit(StrictModel):
    limit: Annotated[StrictInt, Field(ge=1, le=100_000)]
    window_seconds: Annotated[StrictInt, Field(ge=1, le=3600)]


class AbuseConfig(StrictModel):
    auto_ban_enabled: StrictBool = False
    strike_limit: Annotated[StrictInt, Field(ge=2, le=1000)] = 10
    window_seconds: Annotated[StrictInt, Field(ge=10, le=3600)] = 60
    ban_seconds: Annotated[StrictInt, Field(ge=30, le=3600)] = 300


class Route(StrictModel):
    id: ConfigId
    name: Name
    path: StrictStr
    methods: Annotated[tuple[SupportedMethod, ...], Field(min_length=1)]
    max_body_bytes: Annotated[StrictInt, Field(ge=0, le=1_048_576)]
    content_types: tuple[StrictStr, ...] = ()
    ip_rate: RateLimit | None = None
    json_schema: dict[str, object] | None = None

    @field_validator("methods", "content_types", mode="before")
    @classmethod
    def json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class Service(StrictModel):
    id: ConfigId
    name: Name
    public_host: StrictStr
    upstream_id: ConfigId
    enabled: StrictBool
    unmatched_action: Literal["baseline", "deny"]
    max_body_bytes: Annotated[StrictInt, Field(ge=0, le=1_048_576)]
    ip_rate: RateLimit
    abuse: AbuseConfig = Field(default_factory=AbuseConfig)
    routes: Annotated[tuple[Route, ...], Field(max_length=100)] = ()

    @field_validator("routes", mode="before")
    @classmethod
    def json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class Config(StrictModel):
    schema_version: Literal[1]
    service: Service


class RegisteredUpstream(StrictModel):
    id: ConfigId
    name: Name
    scheme: Literal["http", "https"]
    host: StrictStr
    port: Annotated[StrictInt, Field(ge=1, le=65535)]


class Registry(StrictModel):
    upstreams: tuple[RegisteredUpstream, ...]

    @field_validator("upstreams", mode="before")
    @classmethod
    def json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


@dataclass(frozen=True, slots=True)
class CompiledRoute:
    route: Route
    segments: tuple[str, ...]
    literal_count: int


@dataclass(frozen=True, slots=True)
class CompiledConfig:
    document: Config
    upstream: RegisteredUpstream
    routes: tuple[CompiledRoute, ...]


@dataclass(frozen=True, slots=True)
class AppliedConfig:
    version: int
    compiled: CompiledConfig


class PendingApply(StrictModel):
    desired_version: StrictInt
    applied_version: StrictInt | None
    status: Literal["pending"] = "pending"


class Admission(StrictModel):
    allowed: StrictBool
    code: StrictStr | None
    status: StrictInt | None
    retry_after: StrictInt | None
    client_digest: StrictStr


class Violation(StrictModel):
    code: StrictStr
    status: StrictInt
    message: StrictStr
    field_paths: tuple[StrictStr, ...] = ()


class BanView(StrictModel):
    ban_id: StrictStr
    client_digest: StrictStr
    source: Literal["manual", "automatic"]
    created_at_ms: Millis
    expires_at_ms: Millis
    revoked_at_ms: Millis | None
    status: Literal["active", "expired", "revoked"]
    reason_code: StrictStr


class RevokeResult(StrictModel):
    ban_id: StrictStr
    revoked: StrictBool


class CaseResult(StrictModel):
    case_id: StrictStr
    expected: StrictStr
    actual: StrictStr
    outcome: Literal["passed", "failed", "error"]
    request_id: StrictStr | None
    elapsed_ms: Annotated[StrictInt, Field(ge=0)]
    origin_receipt_delta: Annotated[StrictInt, Field(ge=0)]


class FuzzSummary(StrictModel):
    run_id: StrictStr
    profile_id: Literal["core-demo-v1"]
    seed: Annotated[StrictInt, Field(ge=0, le=2_147_483_647)]
    state: Literal["queued", "running", "passed", "failed", "error", "timed_out", "interrupted"]
    created_at_ms: Millis
    started_at_ms: Millis | None
    finished_at_ms: Millis | None
    passed_count: Annotated[StrictInt, Field(ge=0)]
    failed_count: Annotated[StrictInt, Field(ge=0)]
    error_count: Annotated[StrictInt, Field(ge=0)]


class ErrorDetail(StrictModel):
    code: StrictStr
    message: StrictStr
    request_id: StrictStr


class ErrorResponse(StrictModel):
    error: ErrorDetail


class RequestEvent(StrictModel):
    request_id: StrictStr
    at_ms: Millis
    config_version: StrictInt | None
    route_id: StrictStr | None
    method: StrictStr
    decision: Literal["forwarded", "blocked", "gateway_error", "upstream_error", "client_disconnected"]
    reason_code: StrictStr
    status_code: StrictInt | None
    upstream_status: StrictInt | None
    client_digest: StrictStr | None
    duration_ms: Annotated[StrictInt, Field(ge=0)]
    request_bytes: Annotated[StrictInt, Field(ge=0)]
    response_bytes: Annotated[StrictInt, Field(ge=0)]
    origin_attempted: StrictBool
    truncated: StrictBool


class ConfigInvalid(ValueError):
    """Safe validation errors suitable for a CONFIG_INVALID response."""

    def __init__(self, errors: list[str] | tuple[str, ...]):
        self.errors = tuple(errors[:20])
        super().__init__("; ".join(self.errors))
