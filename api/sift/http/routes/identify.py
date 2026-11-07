import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Path, UploadFile
from starlette.concurrency import run_in_threadpool

from ...agent.identify import identify
from ...core.errors import InvalidInput, TooLarge
from ...core.security import check_pixels, sniff_image
from ..deps import Container, Identity, container, identity

router = APIRouter(tags=["identify"])

MAX_EDGE = 1024


async def _read_capped(upload: UploadFile, limit: int) -> bytes:
    raw = await upload.read(limit + 1)
    if len(raw) > limit:
        raise TooLarge(f"Uploads must be under {limit // (1024 * 1024)} MB.")
    return raw


def _frame_jpeg(raw: bytes) -> bytes:
    """Decode the upload and re-encode it as a JPEG no larger than 1024 px on the long edge."""
    try:
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as exc:  # OPENCV_IO_MAX_IMAGE_PIXELS (set in sift/__init__.py) refused it
        raise TooLarge("The photo has too many pixels. Use a photo under 50 megapixels.") from exc
    if img is None:
        raise InvalidInput("The upload isn't a readable image.")
    h, w = img.shape[:2]
    scale = MAX_EDGE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise InvalidInput("The upload isn't a readable image.")
    return enc.tobytes()


@router.post("/v1/identify", summary="Name the food a camera frame shows (Muse vision; offline asks the user)")
async def post_identify(image: UploadFile = File(...), who: Identity = Depends(identity),
                        c: Container = Depends(container)) -> dict:
    c.limiter.hit("agent", who.key_prefix or who.ip, c.settings.limits.rate_agent)
    raw = await _read_capped(image, c.settings.limits.max_image_bytes)
    sniff_image(raw)
    check_pixels(raw)
    # Image work and the model call block; keep them off the event loop.
    frame = await run_in_threadpool(_frame_jpeg, raw)
    return await run_in_threadpool(identify, c.client, frame)


@router.get("/v1/products/{barcode}", summary="Look a barcode up on Open Food Facts and map it to a food")
def get_product(barcode: str = Path(pattern=r"^[0-9]{6,14}$"), who: Identity = Depends(identity),
                c: Container = Depends(container)) -> dict:
    return c.products.lookup(barcode)
