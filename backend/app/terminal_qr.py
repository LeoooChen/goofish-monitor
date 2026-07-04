from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import cast

from PIL import Image


def image_bytes_to_terminal_blocks(image_bytes: bytes, width: int = 48) -> str:
    image = Image.open(BytesIO(image_bytes)).convert("L")
    aspect = image.height / max(image.width, 1)
    height = max(12, int(width * aspect * 0.5))
    resized = image.resize((width, height))
    lines: list[str] = []
    for y in range(resized.height):
        chars: list[str] = []
        for x in range(resized.width):
            pixel = cast(int, resized.getpixel((x, y)))
            chars.append("  " if pixel > 160 else "██")
        lines.append("".join(chars).rstrip())
    return "\n".join(lines)


def save_image_bytes(path: Path, image_bytes: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
