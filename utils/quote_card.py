import io
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


CARD_W   = 800
PAD      = 48
BG_DARK  = (10, 10, 20)
BG_MID   = (20, 10, 45)
CYAN     = (0, 180, 204)
CYAN_DIM = (0, 80, 100)
WHITE    = (255, 255, 255)
GREY     = (160, 160, 180)
CORNER_R = 16


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "arial.ttf",
        "Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        try:
            w = font.getlength(candidate)
        except AttributeError:
            w = len(candidate) * (getattr(font, "size", 16) * 0.6)
        if w <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def generate_quote_card(
    content: str,
    author_name: str,
    quoted_by: str,
    server_name: str,
    avatar_bytes: Optional[bytes],
    timestamp: str,
) -> io.BytesIO:
    font_qmark  = _load_font(88)
    font_body   = _load_font(26)
    font_author = _load_font(20)
    font_small  = _load_font(15)

    if len(content) > 400:
        content = content[:397] + "…"

    lines  = _wrap_text(content, font_body, CARD_W - PAD * 2 - 20)
    line_h = 38
    card_h = max(PAD + 56 + len(lines) * line_h + 30 + 70 + PAD, 280)

    img  = Image.new("RGB", (CARD_W, card_h), BG_DARK)
    draw = ImageDraw.Draw(img)

    # Gradient background
    for x in range(CARD_W):
        t = x / CARD_W
        draw.line(
            [(x, 0), (x, card_h)],
            fill=(
                int(BG_DARK[0] + (BG_MID[0] - BG_DARK[0]) * t),
                int(BG_DARK[1] + (BG_MID[1] - BG_DARK[1]) * t),
                int(BG_DARK[2] + (BG_MID[2] - BG_DARK[2]) * t),
            ),
        )

    # Subtle grid
    for x in range(0, CARD_W, 60):
        draw.line([(x, 0), (x, card_h)], fill=(0, 50, 70))
    for y in range(0, card_h, 40):
        draw.line([(0, y), (CARD_W, y)], fill=(0, 50, 70))

    # Left accent bar
    draw.rectangle([0, 0, 5, card_h], fill=CYAN)

    # Opening quotation mark
    draw.text((PAD - 4, PAD - 28), "“", font=font_qmark, fill=CYAN_DIM)

    # Quote body
    y = PAD + 48
    for line in lines:
        draw.text((PAD, y), line, font=font_body, fill=WHITE)
        y += line_h

    # Closing quotation mark
    draw.text((CARD_W - PAD - 52, y - 20), "”", font=font_qmark, fill=CYAN_DIM)

    # Divider
    sep_y = y + 22
    draw.line([(PAD, sep_y), (CARD_W - PAD, sep_y)], fill=CYAN_DIM, width=1)

    # Author avatar
    av_y    = sep_y + 14
    av_size = 44
    if avatar_bytes:
        try:
            av_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((av_size, av_size))
            mask   = Image.new("L", (av_size, av_size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, av_size - 1, av_size - 1), fill=255)
            ring = Image.new("RGBA", (av_size + 4, av_size + 4), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse((0, 0, av_size + 3, av_size + 3), fill=(*CYAN, 255))
            img.paste(ring, (PAD - 2, av_y - 2), ring)
            img.paste(av_img, (PAD, av_y), mask)
        except Exception:
            pass

    tx = PAD + av_size + 12
    draw.text((tx, av_y + 2),  author_name,                      font=font_author, fill=WHITE)
    draw.text((tx, av_y + 26), f"{server_name}  ·  {timestamp}", font=font_small,  fill=GREY)

    # "Quoted by" aligned right
    qb = f"quoted by {quoted_by}"
    try:
        qb_w = int(font_small.getlength(qb))
    except AttributeError:
        qb_w = len(qb) * 9
    draw.text((CARD_W - PAD - qb_w, av_y + 14), qb, font=font_small, fill=CYAN_DIM)

    # Rounded border overlay
    border = Image.new("RGBA", (CARD_W, card_h), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        (0, 0, CARD_W - 1, card_h - 1), radius=CORNER_R, outline=(*CYAN, 180), width=2
    )
    img.paste(border, mask=border)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
