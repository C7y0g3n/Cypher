import io
import math
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont


CARD_W, CARD_H = 934, 282
AVATAR_SIZE = 200
AVATAR_X, AVATAR_Y = 40, 41
BAR_X, BAR_Y = 270, 220
BAR_W, BAR_H = 610, 28
CORNER_R = 20

BG_DARK = (10, 10, 20)
BG_MID = (20, 10, 45)
CYAN = (0, 180, 204)
CYAN_DIM = (0, 100, 120)
WHITE = (255, 255, 255)
GREY = (160, 160, 180)
DARK_OVERLAY = (0, 0, 0, 160)


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


def _circle_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    return mask


def _gradient_bg() -> Image.Image:
    img = Image.new("RGB", (CARD_W, CARD_H), BG_DARK)
    draw = ImageDraw.Draw(img)
    for x in range(CARD_W):
        ratio = x / CARD_W
        r = int(BG_DARK[0] + (BG_MID[0] - BG_DARK[0]) * ratio)
        g = int(BG_DARK[1] + (BG_MID[1] - BG_DARK[1]) * ratio)
        b = int(BG_DARK[2] + (BG_MID[2] - BG_DARK[2]) * ratio)
        draw.line([(x, 0), (x, CARD_H)], fill=(r, g, b))
    # subtle grid lines
    for x in range(0, CARD_W, 60):
        draw.line([(x, 0), (x, CARD_H)], fill=(0, 60, 80, 40))
    for y in range(0, CARD_H, 40):
        draw.line([(0, y), (CARD_W, y)], fill=(0, 60, 80, 40))
    return img


def generate_rank_card(
    username: str,
    avatar_bytes: Optional[bytes],
    level: int,
    rank_name: str,
    xp: int,
    xp_next: int,
    xp_prev: int,
    leaderboard_rank: int,
) -> io.BytesIO:
    img = _gradient_bg()
    draw = ImageDraw.Draw(img)

    # Avatar
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((AVATAR_SIZE, AVATAR_SIZE))
            mask = _circle_mask(AVATAR_SIZE)
            # Cyan ring
            ring = Image.new("RGBA", (AVATAR_SIZE + 8, AVATAR_SIZE + 8), (0, 0, 0, 0))
            ring_draw = ImageDraw.Draw(ring)
            ring_draw.ellipse((0, 0, AVATAR_SIZE + 7, AVATAR_SIZE + 7), fill=(*CYAN, 255))
            img.paste(ring, (AVATAR_X - 4, AVATAR_Y - 4), ring)
            img.paste(av, (AVATAR_X, AVATAR_Y), mask)
        except Exception:
            pass

    # Fonts
    font_big = _load_font(36)
    font_med = _load_font(24)
    font_sm = _load_font(18)
    font_xs = _load_font(14)

    # Username
    draw.text((270, 50), username, font=font_big, fill=WHITE)

    # Rank name tag
    tag_text = f"  {rank_name}  "
    bbox = draw.textbbox((0, 0), tag_text, font=font_sm)
    tag_w = bbox[2] - bbox[0] + 12
    draw.rounded_rectangle((270, 100, 270 + tag_w, 130), radius=6, fill=CYAN_DIM)
    draw.text((276, 103), tag_text.strip(), font=font_sm, fill=CYAN)

    # Level
    draw.text((270, 145), f"LEVEL  {level}", font=font_med, fill=GREY)

    # Rank position (top right)
    rank_text = f"RANK  #{leaderboard_rank}"
    bbox2 = draw.textbbox((0, 0), rank_text, font=font_med)
    rx = CARD_W - (bbox2[2] - bbox2[0]) - 30
    draw.text((rx, 50), rank_text, font=font_med, fill=CYAN)

    # XP text
    xp_span = xp_next - xp_prev
    xp_progress = xp - xp_prev
    xp_text = f"{xp_progress:,} / {xp_span:,} XP"
    bbox3 = draw.textbbox((0, 0), xp_text, font=font_xs)
    draw.text((CARD_W - (bbox3[2] - bbox3[0]) - 30, 195), xp_text, font=font_xs, fill=GREY)

    # XP bar background
    draw.rounded_rectangle((BAR_X, BAR_Y, BAR_X + BAR_W, BAR_Y + BAR_H), radius=14, fill=(30, 30, 50))

    # XP bar fill
    if xp_span > 0:
        fill_w = int(BAR_W * min(xp_progress / xp_span, 1.0))
    else:
        fill_w = BAR_W
    if fill_w > 0:
        draw.rounded_rectangle(
            (BAR_X, BAR_Y, BAR_X + fill_w, BAR_Y + BAR_H),
            radius=14,
            fill=CYAN,
        )

    # Rounded card border
    border = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        (0, 0, CARD_W - 1, CARD_H - 1), radius=CORNER_R, outline=(*CYAN, 180), width=2
    )
    img.paste(border, mask=border)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
