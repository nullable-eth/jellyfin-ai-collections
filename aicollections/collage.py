"""2x2 poster collage in poster proportions, so it reads like any cover."""

from __future__ import annotations

import io

from PIL import Image

TILE_W, TILE_H = 300, 450


def collage(posters: list[bytes]) -> bytes | None:
    tiles: list[Image.Image] = []
    for data in posters:
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            continue
        # Cover-fit each poster into its tile.
        scale = max(TILE_W / img.width, TILE_H / img.height)
        img = img.resize((round(img.width * scale), round(img.height * scale)))
        left = (img.width - TILE_W) // 2
        top = (img.height - TILE_H) // 2
        tiles.append(img.crop((left, top, left + TILE_W, top + TILE_H)))
    if not tiles:
        return None
    canvas = Image.new("RGB", (TILE_W * 2, TILE_H * 2))
    for i in range(4):
        # Fewer than four posters: repeat them so the grid is never half empty.
        canvas.paste(tiles[i % len(tiles)], ((i % 2) * TILE_W, (i // 2) * TILE_H))
    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=88)
    return out.getvalue()
