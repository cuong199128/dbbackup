"""Renders the app icon as PNG (multiple sizes) + Windows .ico, matching
the design in assets/icon.svg. Uses Pillow only (no rsvg/Inkscape needed),
so it works offline and in the exact same way on Windows/Linux/CI.
"""
from PIL import Image, ImageDraw, ImageFilter
import math

OUT_DIR = "/home/claude/dbbackup/assets"


def make_icon(size: int) -> Image.Image:
    scale = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # -- background rounded square, blue gradient (approximated with a
    # vertical/diagonal blend) --
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)
    top = (0x5B, 0x9C, 0xFF)
    bottom = (0x2F, 0x6F, 0xE0)
    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        bg_draw.line([(0, y), (size, y)], fill=(r, g, b, 255))
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    pad = int(8 * scale)
    radius = int(56 * scale)
    mask_draw.rounded_rectangle([pad, pad, size - pad, size - pad], radius=radius, fill=255)
    img.paste(bg, (0, 0), mask)

    # -- soft drop shadow layer for the disk stack + badge (drawn as a
    # blurred dark ellipse/circle behind them) --
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    cx, cy = 128 * scale, 118 * scale
    sdraw.ellipse([cx - 66 * scale, cy - 62 * scale, cx + 66 * scale, cy + 66 * scale],
                  fill=(18, 58, 143, 130))
    bx, by, br = 176 * scale, 176 * scale, 54 * scale
    sdraw.ellipse([bx - br, by - br + 4 * scale, bx + br, by + br + 4 * scale],
                  fill=(18, 58, 143, 140))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(2, int(4 * scale))))
    img.alpha_composite(shadow)

    # -- database "cylinder" stack (3 disks) --
    disk_light = (255, 255, 255, 255)
    disk_mid = (220, 232, 255, 255)
    disk_dark = (196, 216, 255, 255)
    outline = (47, 111, 224, 70)

    def disk_ellipse(cy_, ry, fill):
        rx = 62 * scale
        draw.ellipse([128 * scale - rx, cy_ - ry, 128 * scale + rx, cy_ + ry], fill=fill)

    rx = 62 * scale
    ry = 22 * scale
    top_y = 88 * scale
    mid_y = 140 * scale
    bot_y = 162 * scale

    # body rectangles between ellipse centers to fake the cylinder sides
    draw.rectangle([128 * scale - rx, top_y, 128 * scale + rx, bot_y], fill=disk_mid)
    disk_ellipse(bot_y, ry, disk_dark)
    draw.rectangle([128 * scale - rx, top_y, 128 * scale + rx, mid_y], fill=disk_light)
    disk_ellipse(mid_y, ry, disk_mid)
    disk_ellipse(top_y, ry, disk_light)
    draw.ellipse([128 * scale - rx, top_y - ry, 128 * scale + rx, top_y + ry],
                 outline=outline, width=max(1, int(4 * scale)))

    # -- green circular badge with upward arrow (backup / upload) --
    bx, by, br = 176 * scale, 176 * scale, 52 * scale
    draw.ellipse([bx - br, by - br, bx + br, by + br], fill=(30, 140, 60, 255))
    draw.ellipse([bx - br, by - br, bx + br, by + br], outline=(255, 255, 255, 230),
                 width=max(1, int(6 * scale)))

    lw = max(2, int(10 * scale))
    ax0, ay0 = bx, by + 24 * scale
    ax1, ay1 = bx, by - 22 * scale
    draw.line([ax0, ay0, ax1, ay1], fill=(255, 255, 255, 255), width=lw)
    head = 18 * scale
    draw.line([bx - head, ay1 + head, ax1, ay1], fill=(255, 255, 255, 255), width=lw)
    draw.line([bx + head, ay1 + head, ax1, ay1], fill=(255, 255, 255, 255), width=lw)
    # round the joints so the arrow doesn't look chopped
    r = lw / 2
    for (px, py) in [(ax0, ay0), (ax1, ay1), (bx - head, ay1 + head), (bx + head, ay1 + head)]:
        draw.ellipse([px - r, py - r, px + r, py + r], fill=(255, 255, 255, 255))

    return img


sizes = [16, 24, 32, 48, 64, 128, 256]
images = {s: make_icon(s) for s in sizes}

for s, im in images.items():
    im.save(f"{OUT_DIR}/icon_{s}.png")

images[256].save(f"{OUT_DIR}/icon.png")

# Windows .ico: bundle the standard size set into one file
ico_sizes = [16, 24, 32, 48, 64, 128, 256]
images[256].save(
    f"{OUT_DIR}/icon.ico",
    format="ICO",
    sizes=[(s, s) for s in ico_sizes],
)

print("done")
