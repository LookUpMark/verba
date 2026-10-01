#!/usr/bin/env python3
"""Generate the Verba app icon set without external dependencies.

Renders a placeholder brand mark (terracotta rounded square + ivory 'V')
in pure Python and writes:
  icons/32x32.png, icons/128x128.png, icons/128x128@2x.png, icons/icon.png
  icons/icon.icns (PNG-chunk container)
  icons/icon.ico (PNG-payload container)

Replace with the real brand icon via `cargo tauri icon app-icon.png` later.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent / "src-tauri" / "icons"

TERRACOTTA = (201, 100, 66)   # #c96442
IVORY = (250, 249, 245)       # #faf9f5
NEAR_BLACK = (20, 20, 19)     # subtle inner shadow tone
CORNER = 0.18                 # rounded-corner radius as fraction of size


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _inside_rounded_square(x: float, y: float, size: float) -> float:
    """1.0 inside the rounded square, 0.0 outside, feathered over 2px."""
    r = size * CORNER
    pad = size * 0.0
    half = size - pad
    cx0, cy0, cx1, cy1 = pad, pad, half, half
    # distance to the rounded rect (SDF approximation)
    rx = max(cx0 + r - x, x - (cx1 - r), 0.0)
    ry = max(cy0 + r - y, y - (cy1 - r), 0.0)
    if rx > 0 and ry > 0:
        d = (rx * rx + ry * ry) ** 0.5 - r
    else:
        d = max(rx, ry, min(0.0, max(rx, ry)))
    return max(0.0, min(1.0, 1.0 - d / 2.0))


def _inside_v(x: float, y: float, size: float) -> float:
    """1.0 inside the 'V' glyph (two thick strokes), 0.0 outside, 2px feather.

    Coordinates normalized to [0,1]; stroke width proportional to size."""
    u, v = x / size, y / size
    w = 0.155          # half-thickness of each stroke
    top_w = 0.36       # half-width of the V opening
    top_y, bottom_y = 0.26, 0.80
    tip_x = 0.5

    def seg_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
        vx, vy = bx - ax, by - ay
        wx, wy = px - ax, py - ay
        t = max(0.0, min(1.0, (wx * vx + wy * vy) / (vx * vx + vy * vy)))
        dx, dy = px - (ax + t * vx), py - (ay + t * vy)
        return (dx * dx + dy * dy) ** 0.5

    # left stroke: from top-left down to the tip; right stroke mirrors it
    d1 = seg_distance(u, v, tip_x - top_w, top_y, tip_x, bottom_y)
    d2 = seg_distance(u, v, tip_x + top_w, top_y, tip_x, bottom_y)
    d = min(d1, d2)
    return max(0.0, min(1.0, (w - d) / 0.008))


def render(size: int) -> bytes:
    """RGBA PNG bytes for the icon at `size`."""
    ss = 2  # supersampling factor for soft edges
    full = size * ss
    rows: list[bytes] = []
    for py in range(full):
        row = bytearray()
        for px in range(full):
            x = (px + 0.5) / ss
            y = (py + 0.5) / ss
            bg = _inside_rounded_square(x, y, size)
            fg = _inside_v(x, y, size)
            r = _lerp(0, TERRACOTTA[0], bg)
            g = _lerp(0, TERRACOTTA[1], bg)
            b = _lerp(0, TERRACOTTA[2], bg)
            r = _lerp(r, IVORY[0], fg)
            g = _lerp(g, IVORY[1], fg)
            b = _lerp(b, IVORY[2], fg)
            row += bytes((int(r), int(g), int(b), int(bg * 255)))
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _downscale(png_size: int, target: int) -> bytes:
    # render at target directly (crisp enough at these sizes, no resampling needed)
    return render(target)


def write_icns(path: Path, sizes: dict[str, int]) -> None:
    chunks = b""
    for code, px in sizes.items():
        data = _downscale(0, px)
        chunks += code.encode() + struct.pack(">I", len(data) + 8) + data
    blob = b"icns" + struct.pack(">I", len(chunks) + 8) + chunks
    path.write_bytes(blob)


def write_ico(path: Path, sizes: list[int]) -> None:
    images = [(s, _downscale(0, s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    offset = 6 + 16 * len(images)
    payload = b""
    for s, data in images:
        w = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    path.write_bytes(header + entries + payload)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, px in {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 512,
        "StoreLogo.png": 512,
    }.items():
        (OUT / name).write_bytes(_downscale(0, px))
        print(f"icons/{name}")
    write_icns(OUT / "icon.icns", {"icp4": 16, "icp5": 32, "icp6": 64, "ic07": 128, "ic08": 256, "ic09": 512, "ic10": 1024})
    print("icons/icon.icns")
    write_ico(OUT / "icon.ico", [16, 24, 32, 48, 64, 128, 256])
    print("icons/icon.ico")
    print(f"done -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
