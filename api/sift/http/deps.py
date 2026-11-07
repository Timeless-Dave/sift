"""Dependency wiring: one container per app, plus auth and rate-limit dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, Request

from ..agent.client import MetaClient
from ..agent.lab_agent import LabAgent
from ..core.config import Settings
from ..core.errors import Unauthorized
from ..core.security import RateLimiter, hash_key
from ..data.store import Store
from ..services.runs import CalibrationService, RunService


@dataclass
class Container:
    settings: Settings
    store: Store
    client: MetaClient
    agent: LabAgent
    runs: RunService
    calibration: CalibrationService
    limiter: RateLimiter

    @classmethod
    def build(cls, settings: Settings) -> Container:
        store = Store(settings.db_path)
        client = MetaClient(settings)
        agent = LabAgent(client)
        return cls(settings, store, client, agent, RunService(settings, store, client, agent),
                   CalibrationService(store), RateLimiter())


def container(request: Request) -> Container:
    return request.app.state.container


def client_ip(request: Request, c: Container) -> str:
    if c.settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@dataclass
class Identity:
    key_prefix: str | None
    ip: str

    @property
    def keyed(self) -> bool:
        return self.key_prefix is not None


def identity(request: Request, x_sift_key: str | None = Header(default=None),
             c: Container = Depends(container)) -> Identity:
    ip = client_ip(request, c)
    if x_sift_key:
        if not c.store.use_key(hash_key(x_sift_key)):
            raise Unauthorized("Unknown or revoked API key.")
        who = Identity(x_sift_key[:12], ip)
    elif c.settings.require_api_key:
        raise Unauthorized("This server requires an X-Sift-Key header.")
    else:
        who = Identity(None, ip)
    c.limiter.hit("api", who.key_prefix or ip,
                  c.settings.limits.rate_keyed if who.keyed else c.settings.limits.rate_public)
    return who


def viewer(x_sift_key: str | None = Header(default=None), c: Container = Depends(container)) -> str | None:
    """For the open catalog: the caller's key prefix if they sent a valid key, else None.
    Unlike `identity`, it neither demands a key nor counts against the rate limit."""
    if not x_sift_key:
        return None
    if not c.store.use_key(hash_key(x_sift_key)):
        raise Unauthorized("Unknown or revoked API key.")
    return x_sift_key[:12]


def require_tier(tier: str, who: Identity) -> None:
    if tier == "enterprise" and not who.keyed:
        raise Unauthorized("The enterprise tier needs an API key (X-Sift-Key).")
