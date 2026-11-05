"""Generate assets/icon.png and assets/icon.ico (run: python tools/make_icon.py)."""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "assets" / "fonts" / "DejaVuSans-Bold.ttf"
N = 1024  # master canvas; everything is drawn here and downscaled (supersampling)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(size, c1, c2):
    """Diagonal gradient, top-left -> bottom-right."""
    g = Image.linear_gradient("L").resize((size, size))           # vertical 0..255
    diag = ImageChops.add(g, g.rotate(90).transpose(Image.FLIP_LEFT_RIGHT), scale=2)
    return Image.composite(Image.new("RGB", (size, size), c2), Image.new("RGB", (size, size), c1), diag)


def shadow(mask, blur, offset, alpha):
    sh = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    sh.putalpha(mask.point(lambda v: v * alpha // 255))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    out = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    out.paste(sh, offset, sh)
    return out


def rounded_mask(box, radius):
    m = Image.new("L", (N, N), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


def master(detail=True):
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))

    # --- background tile: deep blue -> indigo with a soft top highlight
    tile = rounded_mask((40, 40, N - 40, N - 40), 220)
    bg = gradient(N, (59, 130, 246), (30, 41, 130)).convert("RGBA")
    hl = Image.new("RGBA", (N, N), (255, 255, 255, 0))
    ImageDraw.Draw(hl).ellipse((-200, -520, N + 200, 420), fill=(255, 255, 255, 46))
    hl = hl.filter(ImageFilter.GaussianBlur(45))
    bg = Image.alpha_composite(bg, hl)
    img.paste(bg, (0, 0), tile)

    # --- white page with folded corner
    px0, py0, px1, py1, fold = 172, 150, 652, 800, 150
    page = Image.new("L", (N, N), 0)
    d = ImageDraw.Draw(page)
    d.polygon([(px0 + 40, py0), (px1 - fold, py0), (px1, py0 + fold), (px1, py1 - 40),
               (px1 - 40, py1), (px0 + 40, py1), (px0, py1 - 40), (px0, py0 + 40)], fill=255)
    d.pieslice((px0, py0, px0 + 80, py0 + 80), 180, 270, fill=255)
    d.pieslice((px1 - 80, py1 - 80, px1, py1), 0, 90, fill=255)
    d.pieslice((px0, py1 - 80, px0 + 80, py1), 90, 180, fill=255)
    img = Image.alpha_composite(img, shadow(page, 28, (0, 26), 110))
    pg = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    pg.paste(gradient(N, (255, 255, 255), (222, 230, 247)).convert("RGBA"), (0, 0), page)
    img = Image.alpha_composite(img, pg)
    d = ImageDraw.Draw(img)
    d.polygon([(px1 - fold, py0), (px1, py0 + fold), (px1 - fold, py0 + fold)], fill=(176, 196, 240))

    # --- text lines on the page
    if detail:
        for i, w in enumerate((330, 270, 330, 200)):
            y = 290 + i * 72
            d.rounded_rectangle((px0 + 70, y, px0 + 70 + w, y + 30), radius=15, fill=(150, 170, 215))

    # --- red PDF badge, overlapping bottom-right
    bx0, by0, bx1, by1 = 352, 560, 852, 800
    badge = rounded_mask((bx0, by0, bx1, by1), 50)
    img = Image.alpha_composite(img, shadow(badge, 22, (0, 18), 140))
    red = gradient(N, (244, 80, 80), (200, 30, 50)).convert("RGBA")
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    layer.paste(red, (0, 0), badge)
    img = Image.alpha_composite(img, layer)
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(str(FONT), 168)
    d.text(((bx0 + bx1) // 2, (by0 + by1) // 2 + 6), "PDF", font=f, fill="white", anchor="mm")
    return img


def main():
    big = master(True)
    big.resize((512, 512), Image.LANCZOS).save(ROOT / "assets" / "icon.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = []
    for s in sizes:
        src = master(detail=s >= 48) if s < 48 else big
        frames.append(src.resize((s, s), Image.LANCZOS))
    frames[-1].save(ROOT / "assets" / "icon.ico", sizes=[(s, s) for s in sizes],
                    append_images=frames[:-1])
    print("icon written")


if __name__ == "__main__":
    main()
