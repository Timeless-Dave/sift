from fastapi import APIRouter, Depends, File, UploadFile
from starlette.concurrency import run_in_threadpool

from ...agent.client import MetaUnavailable
from ...core.errors import Conflict, TooLarge, Unavailable
from ...core.security import sniff_audio
from ...domain import registry
from ..deps import Container, Identity, container, identity, require_tier
from ..schemas import AgentTurn

router = APIRouter(tags=["agent"])


@router.post("/v1/agent/turn", summary="One turn with the Lab Agent for the current protocol step")
def agent_turn(body: AgentTurn, who: Identity = Depends(identity), c: Container = Depends(container)) -> dict:
    require_tier(body.tier, who)
    c.limiter.hit("agent", who.key_prefix or who.ip, c.settings.limits.rate_agent)
    assay = registry.get(body.assay_id)
    if not registry.is_runnable(assay):
        raise Conflict(f"'{assay['name']}' is planned, not runnable yet.")
    return c.agent.turn(body.assay_id, body.step_id, [m.model_dump() for m in body.history], body.message,
                        body.tier, c.settings.limits.max_user_text, c.settings.limits.max_history)


@router.post("/v1/transcribe", summary="Speech to text for hands-free control (needs the Meta Model API key)")
async def transcribe(audio: UploadFile = File(...), who: Identity = Depends(identity),
                     c: Container = Depends(container)) -> dict:
    """Voice has no offline mode: without a key, or when Meta is unreachable, this answers 503."""
    c.limiter.hit("agent", who.key_prefix or who.ip, c.settings.limits.rate_agent)
    limit = c.settings.limits.max_audio_bytes
    raw = await audio.read(limit + 1)
    if len(raw) > limit:
        raise TooLarge(f"Audio must be under {limit // (1024 * 1024)} MB.")
    mime = sniff_audio(raw)
    if not c.client.online:
        raise Unavailable("Voice needs the Meta Model API key on the server.")
    try:
        text = await run_in_threadpool(c.client.transcribe, raw, "voice." + mime.split("/")[1], mime)
    except MetaUnavailable as exc:
        raise Unavailable("Voice is unavailable right now. Type your message instead.") from exc
    return {"text": text[: c.settings.limits.max_user_text], "agent": "muse-voice"}
