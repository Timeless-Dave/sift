"""Decode SAM 3.1 mask payloads from the Meta Model API Responses lane.

A mask token carries ``data=H,W,<marker><base85>`` where the marker is ``~``
(lossless, the API default) or ``!`` (one_bit, requested through
``metadata.mask_encoding``). The body is a five-character base85 length prefix
followed by an arithmetic-coded raster. Format reference: the "Mask payload
encoding" section of protocol/sam3.md in meta-models/meta-sam and
dev.meta.ai/docs/sam/reading-segmentation.

Stdlib only, no third-party parser dependency.
"""

from __future__ import annotations

from array import array

__all__ = ["MAX_MASK_AREA", "MaskError", "decode"]


class MaskError(ValueError):
    """A mask payload is malformed or fails its integrity checks."""


# Client-side guards. Real SAM rasters are small (tens of thousands of pixels);
# anything larger is rejected so a corrupt response cannot burn memory or CPU.
MAX_MASK_AREA = 1024 * 1024
MAX_PACKED_BYTES = 64 * 1024 * 1024

_SAFE_INT = (1 << 53) - 1
_DIGITS = ("!#$%&'()*+-./0123456789:=?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`"
           "abcdefghijklmnopqrstuvwxyz{")
assert len(_DIGITS) == 85
_VALUE = [-1] * 128
for _index, _char in enumerate(_DIGITS):
    _VALUE[ord(_char)] = _index

_TOP = 1 << 24
_BOTTOM = 1 << 16
_U32 = 0xFFFFFFFF

# one_bit context model.
_CTX_INCREMENT = 14
_CTX_LIMIT = 4096
_CTX_COUNT = 1 << 12
_CTX_PAD = 2

# Lossless residual model.
_ZERO_INCREMENT = 32
_ZERO_LIMIT = 16384
_O1_INCREMENT = 56
_O1_LIMIT = 8192
_O2_STEP = 14 * 44
_O2_LIMIT = 14 * 3584
_O0_STEP = 32
_O0_LIMIT = 4096
_MODES = 5


def decode(payload: str, width: int, height: int) -> bytes:
    """Decode one mask payload (marker included) to row-major 0/1 bytes of ``width * height``."""
    if isinstance(width, bool) or isinstance(height, bool) or not isinstance(width, int) \
            or not isinstance(height, int):
        raise MaskError("Mask dimensions must be integers.")
    if width <= 0 or height <= 0:
        raise MaskError("Mask dimensions must be positive.")
    if width * height > MAX_MASK_AREA:
        raise MaskError(f"Mask raster {width}x{height} exceeds the {MAX_MASK_AREA}-pixel cap.")
    if not isinstance(payload, str) or len(payload) < 2:
        raise MaskError("Mask payload is missing.")
    marker, body = payload[0], payload[1:]
    try:
        if marker == "~":
            return _decode_lossless(body, width, height)
        if marker == "!":
            raster = _decode_one_bit(body, width, height)
            if _encode_one_bit(raster, width, height) != payload:
                raise MaskError("Mask payload is not canonical or has invalid finalization.")
            return raster
    except MaskError:
        raise
    except MemoryError:
        raise
    except Exception as exc:
        raise MaskError("Mask payload could not be decoded.") from exc
    raise MaskError("Mask payload must start with '~' (lossless) or '!' (one_bit).")


def _digit(char: str) -> int:
    code = ord(char)
    value = _VALUE[code] if code < 128 else -1
    if value < 0:
        raise MaskError("Mask payload contains an invalid character.")
    return value


def _pack(data: bytes) -> str:
    size = len(data)
    out = [_DIGITS[(size // 85 ** i) % 85] for i in range(4, -1, -1)]
    full = size - size % 4
    for offset in range(0, full, 4):
        value = int.from_bytes(data[offset:offset + 4], "big")
        digits = [(value // 85 ** i) % 85 for i in range(4, -1, -1)]
        out.extend(_DIGITS[d] for d in digits)
    tail = size - full
    if tail:
        value = int.from_bytes(data[full:] + b"\0" * (4 - tail), "big")
        digits = [(value // 85 ** i) % 85 for i in range(4, -1, -1)]
        out.extend(_DIGITS[d] for d in digits[:tail + 1])
    return "".join(out)


def _unpack(text: str) -> bytes:
    # Lengths count UTF-16 code units the way the cross-language contract does.
    units = sum(2 if ord(c) > 0xFFFF else 1 for c in text)
    if units < 5:
        raise MaskError("Mask payload is missing its length prefix.")
    size = 0
    for char in text[:5]:
        size = size * 85 + _digit(char)
    if size > _SAFE_INT:
        raise MaskError("Mask payload length is unsupported.")
    if size > MAX_PACKED_BYTES:
        raise MaskError("Mask payload is too large.")
    tail = size % 4
    if units != 5 + (size // 4) * 5 + (0 if tail == 0 else tail + 1):
        raise MaskError("Mask payload length does not match its prefix.")
    out = bytearray(size)
    pos = 5
    full = size - tail
    for dest in range(0, full, 4):
        value = 0
        for i in range(5):
            value = value * 85 + _digit(text[pos + i])
        if value > _U32:
            raise MaskError("Mask payload contains an out-of-range group.")
        pos += 5
        out[dest:dest + 4] = value.to_bytes(4, "big")
    if tail:
        value = 0
        for i in range(5):
            value = value * 85 + (_digit(text[pos + i]) if i < tail + 1 else 84)
        if value > _U32:
            raise MaskError("Mask payload contains an out-of-range tail.")
        out[full:] = value.to_bytes(4, "big")[:tail]
    if _pack(bytes(out)) != text:
        raise MaskError("Mask payload is not in canonical form.")
    return bytes(out)


class _Encoder:
    __slots__ = ("_low", "_out", "_range")

    def __init__(self) -> None:
        self._low, self._range, self._out = 0, _U32, bytearray()

    def encode(self, cumulative: int, frequency: int, total: int) -> None:
        scaled = self._range // total
        self._low = (self._low + scaled * cumulative) & _U32
        self._range = scaled * frequency
        while True:
            if (self._low ^ ((self._low + self._range) & _U32)) & _U32 < _TOP:
                pass
            elif self._range < _BOTTOM:
                self._range = -self._low & (_BOTTOM - 1)
            else:
                break
            self._out.append(self._low >> 24 & 0xFF)
            self._low = self._low << 8 & _U32
            self._range = self._range << 8 & _U32

    def finish(self) -> bytes:
        for _ in range(4):
            self._out.append(self._low >> 24 & 0xFF)
            self._low = self._low << 8 & _U32
        return bytes(self._out)


class _Decoder:
    __slots__ = ("_code", "_data", "_low", "_pos", "_range", "_scaled")

    def __init__(self, data: bytes):
        if len(data) < 4:
            raise MaskError("Mask payload is missing its finalization.")
        self._data, self._pos = data, 0
        self._low, self._range, self._code, self._scaled = 0, _U32, 0, 0
        for _ in range(4):
            self._code = (self._code << 8 | self._read()) & _U32

    def _read(self) -> int:
        if self._pos >= len(self._data):
            raise MaskError("Mask payload ended before decoding completed.")
        value = self._data[self._pos]
        self._pos += 1
        return value

    def frequency(self, total: int) -> int:
        self._scaled = self._range // total
        if not self._scaled:
            raise MaskError("Mask payload has invalid coding state.")
        value = ((self._code - self._low) & _U32) // self._scaled
        return total - 1 if value >= total else value

    def consume(self, cumulative: int, frequency: int) -> None:
        self._low = (self._low + self._scaled * cumulative) & _U32
        self._range = self._scaled * frequency
        while True:
            if (self._low ^ ((self._low + self._range) & _U32)) & _U32 < _TOP:
                pass
            elif self._range < _BOTTOM:
                self._range = -self._low & (_BOTTOM - 1)
            else:
                break
            self._code = (self._code << 8 | self._read()) & _U32
            self._low = self._low << 8 & _U32
            self._range = self._range << 8 & _U32


def _bump(counts: array[int], offset: int, bit: int) -> None:
    counts[offset + bit] = (counts[offset + bit] + _CTX_INCREMENT) & 0xFFFF
    if counts[offset] + counts[offset + 1] >= _CTX_LIMIT:
        counts[offset] = (counts[offset] >> 1) or 1
        counts[offset + 1] = (counts[offset + 1] >> 1) or 1


def _one_bit_context(padded: bytearray, pos: int, stride: int) -> int:
    prior, earlier = pos - stride, pos - 2 * stride
    return (padded[pos - 1] | padded[pos - 2] << 1 | padded[prior - 2] << 2 | padded[prior - 1] << 3
            | padded[prior] << 4 | padded[prior + 1] << 5 | padded[prior + 2] << 6
            | padded[earlier - 2] << 7 | padded[earlier - 1] << 8 | padded[earlier] << 9
            | padded[earlier + 1] << 10 | padded[earlier + 2] << 11)


def _encode_one_bit(raster: bytes, width: int, height: int) -> str:
    encoder = _Encoder()
    counts = array("H", [1]) * (_CTX_COUNT * 2)
    stride = width + 2 * _CTX_PAD
    padded = bytearray(stride * (height + _CTX_PAD))
    for y in range(height):
        row = (y + _CTX_PAD) * stride + _CTX_PAD
        for x in range(width):
            pos = row + x
            offset = _one_bit_context(padded, pos, stride) << 1
            zero, one = counts[offset], counts[offset + 1]
            bit = raster[y * width + x]
            if bit not in (0, 1):
                raise MaskError("Decoded mask is not binary.")
            encoder.encode(zero if bit else 0, one if bit else zero, zero + one)
            padded[pos] = bit
            _bump(counts, offset, bit)
    return "!" + _pack(encoder.finish())


def _decode_one_bit(body: str, width: int, height: int) -> bytes:
    decoder = _Decoder(_unpack(body))
    counts = array("H", [1]) * (_CTX_COUNT * 2)
    stride = width + 2 * _CTX_PAD
    padded = bytearray(stride * (height + _CTX_PAD))
    out = bytearray(width * height)
    for y in range(height):
        row = (y + _CTX_PAD) * stride + _CTX_PAD
        for x in range(width):
            pos = row + x
            offset = _one_bit_context(padded, pos, stride) << 1
            zero, one = counts[offset], counts[offset + 1]
            bit = 0 if decoder.frequency(zero + one) < zero else 1
            decoder.consume(zero if bit else 0, one if bit else zero)
            padded[pos] = bit
            out[y * width + x] = bit
            _bump(counts, offset, bit)
    return bytes(out)


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    dl, du, dul = abs(estimate - left), abs(estimate - up), abs(estimate - upper_left)
    if dl <= du and dl <= dul:
        return left
    return up if du <= dul else upper_left


def _zero_context(residuals: bytearray, offset: int, x: int, y: int, width: int) -> int:
    left = 1 if x == 0 else int(residuals[offset - 1] == 0)
    up = 1 if y == 0 else int(residuals[offset - width] == 0)
    upper_left = 1 if x == 0 or y == 0 else int(residuals[offset - width - 1] == 0)
    upper_right = 1 if y == 0 or x == width - 1 else int(residuals[offset - width + 1] == 0)
    return left | up << 1 | upper_left << 2 | upper_right << 3


def _predict(out: bytearray, offset: int, x: int, y: int, mode: int, width: int) -> int:
    left = out[offset - 1] if x > 0 else 0
    up = out[offset - width] if y > 0 else 0
    if mode == 1:
        return up
    if mode == 2:
        return left
    if mode == 3:
        return (left + up) >> 1
    upper_left = out[offset - width - 1] if x > 0 and y > 0 else 0
    if mode == 0:
        return _paeth(left, up, upper_left)
    if upper_left >= max(left, up):
        return min(left, up)
    if upper_left <= min(left, up):
        return max(left, up)
    return left + up - upper_left


def _decode_lossless(body: str, width: int, height: int) -> bytes:
    packed = _unpack(body)
    if len(packed) < 5:
        raise MaskError("Lossless mask payload is truncated.")
    mode = packed[0]
    if mode >= _MODES:
        raise MaskError("Lossless mask payload uses an invalid predictor.")
    decoder = _Decoder(packed[1:])
    size = width * height
    out, residuals = bytearray(size), bytearray(size)
    zero_counts = array("I", [1]) * 32
    order_one = array("H", [1]) * (256 * 256)
    one_totals = array("i", [256]) * 256
    order_zero = array("H", [2]) * 256
    zero_total = 512
    order_two: dict[int, array[int]] = {}
    previous = 0
    for offset in range(size):
        x, y = offset % width, offset // width
        zctx = _zero_context(residuals, offset, x, y, width) << 1
        zero, nonzero = zero_counts[zctx], zero_counts[zctx + 1]
        bit = 0 if decoder.frequency(zero + nonzero) < zero else 1
        decoder.consume(zero if bit else 0, nonzero if bit else zero)
        zero_counts[zctx + bit] = (zero_counts[zctx + bit] + _ZERO_INCREMENT) & _U32
        if zero_counts[zctx] + zero_counts[zctx + 1] >= _ZERO_LIMIT:
            zero_counts[zctx] = (zero_counts[zctx] >> 1) or 1
            zero_counts[zctx + 1] = (zero_counts[zctx + 1] >> 1) or 1
        symbol = 0
        if bit:
            key = previous << 8 | (residuals[offset - width] if offset >= width else 0)
            second = order_two.get(key)
            if second is None:
                second = array("H", [0]) * 257
                order_two[key] = second
            first = previous << 8
            total = (second[256] + one_totals[previous] + zero_total
                     - second[0] - order_one[first] - order_zero[0])
            target = decoder.frequency(total)
            cumulative, symbol = 0, 1
            frequency = second[1] + order_one[first + 1] + order_zero[1]
            while cumulative + frequency <= target:
                cumulative += frequency
                symbol += 1
                if symbol >= 256:
                    raise MaskError("Lossless mask payload is malformed.")
                frequency = second[symbol] + order_one[first + symbol] + order_zero[symbol]
            decoder.consume(cumulative, frequency)
            second[symbol] = (second[symbol] + _O2_STEP) & 0xFFFF
            second[256] = (second[256] + _O2_STEP) & 0xFFFF
            if second[256] >= _O2_LIMIT:
                scaled = 0
                for value in range(256):
                    second[value] >>= 1
                    scaled += second[value]
                second[256] = scaled & 0xFFFF
            order_one[first + symbol] = (order_one[first + symbol] + _O1_INCREMENT) & 0xFFFF
            one_totals[previous] = _i32(one_totals[previous] + _O1_INCREMENT)
            if one_totals[previous] >= _O1_LIMIT:
                scaled = 0
                for value in range(256):
                    kept = (order_one[first + value] >> 1) or 1
                    order_one[first + value] = kept
                    scaled += kept
                one_totals[previous] = _i32(scaled)
            order_zero[symbol] = (order_zero[symbol] + _O0_STEP) & 0xFFFF
            zero_total += _O0_STEP
            if zero_total >= _O0_LIMIT:
                scaled = 0
                for value in range(256):
                    order_zero[value] >>= 1
                    scaled += order_zero[value]
                zero_total = scaled
        residuals[offset] = symbol
        delta = -((symbol + 1) >> 1) if symbol & 1 else symbol >> 1
        out[offset] = (_predict(out, offset, x, y, mode, width) + delta) & 0xFF
        previous = symbol
    return bytes(value >= 129 for value in out)


def _i32(value: int) -> int:
    value &= _U32
    return value if value < 1 << 31 else value - (1 << 32)
