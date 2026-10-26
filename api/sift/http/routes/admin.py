from fastapi import APIRouter, Depends, Header, Request

from ...core.errors import NotFound
from ...core.security import check_admin, hash_key, new_api_key
from ..deps import Container, client_ip, container
from ..schemas import KeyRequest

router = APIRouter(tags=["admin"], include_in_schema=False)


def _admin(request: Request, x_admin_token: str | None, c: Container) -> None:
    c.limiter.hit("admin", client_ip(request, c), 10)  # slow down token guessing
    check_admin(x_admin_token, c.settings.admin_token)


@router.post("/v1/keys")
def create_key(body: KeyRequest, request: Request, x_admin_token: str | None = Header(default=None),
               c: Container = Depends(container)) -> dict:
    _admin(request, x_admin_token, c)
    key = new_api_key()
    c.store.create_key(hash_key(key), key[:12], body.owner)
    return {"key": key, "prefix": key[:12], "owner": body.owner,
            "note": "Store this key now. Sift keeps only its hash and can't show it again."}


@router.delete("/v1/keys/{prefix}")
def revoke_key(prefix: str, request: Request, x_admin_token: str | None = Header(default=None),
               c: Container = Depends(container)) -> dict:
    _admin(request, x_admin_token, c)
    if not c.store.revoke_key(prefix):
        raise NotFound("No key with that prefix.")
    return {"ok": True}
