"""Parse SAM 3.1 segmentation output text from a Responses output_text lane.

One line per frame: ``<Nf>id<|box;...|><|mask;...|>,id...``. Boxes are validated
structurally; the mask payload decodes to the binary raster. Wire grammar:
dev.meta.ai/docs/sam/reading-segmentation and protocol/sam3.md in
meta-models/meta-sam. Confidence (``c``) and unknown fields/tokens are accepted
and ignored, matching the reference parsers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import sam_codec

__all__ = ["SamMask", "SamRecord", "decode_mask", "parse_output_text"]


@dataclass(frozen=True, slots=True)
class SamMask:
    """One mask token: encoding derived from the payload marker, raster dims, payload with marker."""

    encoding: str  # "lossless" (~) or "one_bit" (!)
    payload: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class SamRecord:
    """One segmented object: frame index, stable object id, inclusive box (x1, y1, x2, y2, w, h), mask."""

    frame: int
    object_id: int
    box: tuple[int, int, int, int, int, int]
    mask: SamMask


_HEADER = re.compile(r"^<([0-9]+)f(?:;[^>]*)?>(.*)$")
_RECORD = re.compile(r",?([0-9]+)(?=<\|)")
_TOKEN = re.compile(r"<\|([A-Za-z][A-Za-z0-9_.-]*)(?:;([^|]*))?\|>")
_SIGNED = re.compile(r"-?[0-9]+")
_UNSIGNED = re.compile(r"[0-9]+")
_DATA = re.compile(r"([0-9]+),([0-9]+),([!~][^|]+)")
_BOX_KEYS = frozenset({"x1", "y1", "x2", "y2", "w", "h", "c"})
_MASK_KEYS = frozenset({"x", "y", "data", "c"})
_WS = ("\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
       "\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff")
_SAFE_INT = (1 << 53) - 1


def parse_output_text(text: str) -> list[SamRecord]:
    """Parse the first geometry line of SAM output text. Raises ValueError when empty or malformed."""
    if not isinstance(text, str):
        raise ValueError("SAM output text must be a string.")
    for raw in text.splitlines():
        if raw.strip(_WS):
            return _parse_line(raw.strip(_WS))
    raise ValueError("SAM returned no segmentation line.")


def decode_mask(mask: SamMask) -> bytes:
    """Decode a mask to row-major 0/1 bytes of ``width * height``. Raises ValueError when undecodable."""
    return sam_codec.decode(mask.payload, mask.width, mask.height)


def _parse_line(line: str) -> list[SamRecord]:
    header = _HEADER.match(line)
    if header is None:
        raise ValueError("SAM line has no frame marker.")
    frame = int(header.group(1))
    if frame > _SAFE_INT:
        raise ValueError("SAM frame index is out of range.")
    body = header.group(2)
    records: list[SamRecord] = []
    pos = 0
    while pos < len(body):
        start = _RECORD.match(body, pos)
        if start is None:
            raise ValueError("SAM line has a malformed object record.")
        pos = start.end()
        tokens = []
        while (token := _TOKEN.match(body, pos)) is not None:
            tokens.append(token)
            pos = token.end()
        if not tokens:
            raise ValueError("SAM object record has no tokens.")
        records.append(_record(frame, int(start.group(1)), tokens))
    if not records:
        raise ValueError("SAM line carries no object records.")
    return records


def _record(frame: int, object_id: int, tokens: list[re.Match[str]]) -> SamRecord:
    boxes = [t for t in tokens if t.group(1) == "box"]
    masks = [t for t in tokens if t.group(1) == "mask"]
    if len(boxes) != 1 or len(masks) != 1:
        raise ValueError("SAM object record needs one box and one mask.")
    box = _box(_fields(boxes[0].group(2), _BOX_KEYS))
    return SamRecord(frame, object_id, box, _mask(_fields(masks[0].group(2), _MASK_KEYS)))


def _fields(body: str | None, known: frozenset[str]) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for part in [] if body is None else body.split(";"):
        field = part.strip(_WS)
        if not field:
            continue
        key, sep, value = field.partition("=")
        key = key.strip(_WS)
        if key not in known:
            continue
        if key in values:
            if key != "c":
                raise ValueError(f"SAM record repeats {key!r}.")
            values[key] = None  # repeated confidence is ignored, like an absent one
            continue
        values[key] = value.strip(_WS) if sep else None
    return values


def _ints(values: list[str | None], pattern: re.Pattern[str], what: str) -> list[int]:
    out = []
    for value in values:
        if value is None or pattern.fullmatch(value) is None:
            raise ValueError(what)
        try:
            out.append(int(value))
        except ValueError as exc:
            raise ValueError(f"{what} They are out of range.") from exc
    return out


def _box(fields: dict[str, str | None]) -> tuple[int, int, int, int, int, int]:
    coords = _ints([fields.get(k) for k in ("x1", "y1", "x2", "y2")], _SIGNED, "SAM box coordinates are invalid.")
    dims = _ints([fields.get(k) for k in ("w", "h")], _UNSIGNED, "SAM box dimensions are invalid.")
    x1, y1, x2, y2 = coords
    w, h = dims
    if any(abs(v) > _SAFE_INT for v in (x1, y1, x2, y2, w, h)):
        raise ValueError("SAM box coordinates are out of range.")
    if w <= 0 or h <= 0 or x1 < 0 or y1 < 0 or x2 < x1 or y2 < y1 or x2 >= w or y2 >= h:
        raise ValueError("SAM box lies outside its frame.")
    return x1, y1, x2, y2, w, h


def _mask(fields: dict[str, str | None]) -> SamMask:
    if fields.get("x") != "0" or fields.get("y") != "0":
        raise ValueError("SAM mask origin must be x=0;y=0.")
    data = _DATA.fullmatch(fields.get("data") or "")
    if data is None:
        raise ValueError("SAM mask data is malformed.")
    try:
        height, width = int(data.group(1)), int(data.group(2))
    except ValueError as exc:
        raise ValueError("SAM mask dimensions are out of range.") from exc
    payload = data.group(3)
    return SamMask("lossless" if payload.startswith("~") else "one_bit", payload, width, height)
