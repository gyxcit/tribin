"""Génère les icônes d'empaquetage (packaging/tribin.ico et packaging/tribin.icns) avec Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "packaging"
BLUE, DARK, WHITE = (47, 111, 223, 255), (33, 78, 156, 255), (255, 255, 255, 255)


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64
    w = max(1, round(3 * s))
    d.polygon([(14 * s, 20 * s), (50 * s, 20 * s), (46 * s, 58 * s), (18 * s, 58 * s)], fill=BLUE, outline=DARK, width=w)
    d.rounded_rectangle([10 * s, 12 * s, 54 * s, 19 * s], radius=2 * s, fill=BLUE, outline=DARK, width=w)
    d.rectangle([26 * s, 7 * s, 38 * s, 12 * s], fill=BLUE, outline=DARK, width=w)
    for x in (25, 32, 39):
        d.line([(x * s, 27 * s), (x * s, 51 * s)], fill=WHITE, width=max(1, round(2.5 * s)))
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    big = draw(1024)
    big.save(OUT / "tribin.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(OUT / "tribin.icns")
    big.resize((256, 256), Image.LANCZOS).save(OUT / "tribin.png")
    print(f"Icônes écrites dans {OUT}")


if __name__ == "__main__":
    main()
