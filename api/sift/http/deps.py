"""Dependency wiring: one container per app, plus auth and rate-limit dependencies."""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass

from fastapi import Depends, Header, Request

from ..agent.client import MetaClient
from ..agent.lab_agent import LabAgent
from ..core.config import Settings
from ..core.errors import Unauthorized
from ..core.security import RateLimiter, RedisRateLimiter, hash_key
from ..data.store import Store
from ..scan.service import ScanService
from ..services.runs import CalibrationService, RunService

log = logging.getLogger("sift.http.deps")


def build_limiter(settings: Settings) -> RateLimiter:
    """Redis-backed limiter when SIFT_REDIS_URL is set, else the in-process one."""
    if not settings.redis_url:
        return RateLimiter()
    try:
        return RedisRateLimiter.from_url(settings.redis_url)
    except Exception as exc:  # missing package or bad URL: stay up on the in-process limiter
        log.warning("SIFT_REDIS_URL ignored (%s); using the in-process rate limiter.", type(exc).__name__)
        return RateLimiter()


@dataclass
class Container:
    settings: Settings
    store: Store
    client: MetaClient
    agent: LabAgent
    runs: RunService
    calibration: CalibrationService
    limiter: RateLimiter
    scans: ScanService

    @classmethod
    def build(cls, settings: Settings) -> Container:
        store = Store(settings.db_path)
        client = MetaClient(settings)
        agent = LabAgent(client)
        return cls(settings, store, client, agent, RunService(settings, store, client, agent),
                   CalibrationService(store), build_limiter(settings), ScanService(store, agent))


def container(request: Request) -> Container:
    return request.app.state.container


# Peers the API accepts X-Forwarded-For from when SIFT_TRUST_PROXY=1: the Docker
# networks nginx and caddy run on, plus loopback for host-side checks. LAN
# (192.168/16) is deliberately excluded so a direct client can't spoof its IP.
_TRUSTED_PROXY_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)


def _peer_is_trusted_proxy(peer: str | None) -> bool:
    """True when the immediate peer is the Docker-network proxy, never for unknown hosts."""
    if not peer:
        return False
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(ip in net for net in _TRUSTED_PROXY_NETWORKS)


def client_ip(request: Request, c: Container) -> str:
    """IP for rate limiting. With SIFT_TRUST_PROXY=1 and a trusted proxy peer, the last
    X-Forwarded-For entry (the address nginx saw); otherwise the immediate peer."""
    peer = request.client.host if request.client else "unknown"
    if not c.settings.trust_proxy or not _peer_is_trusted_proxy(peer):
        return peer
    fwd = request.headers.get("x-forwarded-for")
    if not fwd:
        return peer
    entries = [e.strip() for e in fwd.split(",") if e.strip()]
    return entries[-1] if entries else peer


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


def viewer(request: Request, x_sift_key: str | None = Header(default=None),
           c: Container = Depends(container)) -> str | None:
    """For the open catalog: the caller's key prefix if they sent a valid key, else None.
    Unlike `identity`, it never demands a key, but it counts against the rate limit."""
    ip = client_ip(request, c)
    if not x_sift_key:
        c.limiter.hit("catalog", ip, c.settings.limits.rate_catalog)
        return None
    if not c.store.use_key(hash_key(x_sift_key)):
        raise Unauthorized("Unknown or revoked API key.")
    c.limiter.hit("catalog", x_sift_key[:12], max(c.settings.limits.rate_keyed, c.settings.limits.rate_catalog))
    return x_sift_key[:12]


def require_tier(tier: str, who: Identity) -> None:
    if tier == "enterprise" and not who.keyed:
        raise Unauthorized("The enterprise tier needs an API key (X-Sift-Key).")


def require_calibration_key(who: Identity = Depends(identity), c: Container = Depends(container)) -> Identity:
    """For calibration writes: when SIFT_PROTECT_CALIBRATION=1, anonymous callers get a 401."""
    if c.settings.protect_calibration and not who.keyed:
        raise Unauthorized("Calibration writes need an API key (X-Sift-Key) on this server.")
    return who
