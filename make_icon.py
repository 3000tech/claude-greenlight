"""One-shot generator for monitor.ico — run once, commit the .ico."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "monitor.ico"
BASE = 256

BG = (28, 28, 32, 255)        # near-black slate
BG_EDGE = (52, 52, 58, 255)   # subtle bevel
CORAL = (217, 119, 87, 255)   # Claude coral
DOT = (34, 197, 94, 255)      # active-session green
DOT_RING = (15, 30, 20, 255)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    radius = int(size * 0.22)
    # 1px inner edge for a soft bevel
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=BG_EDGE)
    pad = max(1, size // 64)
    d.rounded_rectangle(
        (pad, pad, size - 1 - pad, size - 1 - pad),
        radius=max(1, radius - pad),
        fill=BG,
    )

    # Centered "C" — Claude coral
    font = _font(int(size * 0.78))
    text = "C"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1] - int(size * 0.02)
    d.text((tx, ty), text, font=font, fill=CORAL)

    # Active-session dot, bottom-right — only on sizes where it reads cleanly
    if size >= 24:
        r = max(2, int(size * 0.13))
        margin = int(size * 0.10)
        cx = size - margin - r
        cy = size - margin - r
        # tiny dark ring so the dot pops on any background
        ring = max(1, size // 64)
        d.ellipse((cx - r - ring, cy - r - ring, cx + r + ring, cy + r + ring), fill=DOT_RING)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=DOT)

    return img


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = render(BASE)
    images = [base.resize((s, s), Image.LANCZOS) if s != BASE else base for s in sizes]
    images[0].save(OUT, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[1:])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
