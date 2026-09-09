"""
render_text.py

Helper render teks (termasuk emoji warna) menjadi gambar PNG transparan.

Kenapa Pillow, bukan ffmpeg drawtext:
  - filter `drawtext` ffmpeg hanya bisa render glyph monokrom dari font
    biasa (DynaPuff/DejaVu), dan tidak mendukung emoji berwarna.
  - Noto Color Emoji (format CBDT bitmap) hanya punya strike ukuran tetap
    (109px). Pillow/FreeType me-render strike itu, lalu kita downscale ke
    ukuran tampilan target sehingga emoji tampil penuh warna.

Strategi rendering:
  1. Semua font (teks biasa + emoji) di-render pada ukuran "render"
     (= 109, satu-satunya strike valid) agar metrik konsisten & konsisten.
  2. Setiap baris dipecah jadi "run": segmen teks biasa (font DynaPuff + strok)
     dan segmen emoji (Noto Color Emoji berwarna, embedded_color=True).
  3. Run ditata berurutan dalam satu baris, baris ditumpuk dengan line_spacing.
  4. Seluruh kanvas di-downscale (LANCZOS) ke ukuran tampilan target (`size`).
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

# Satu-satunya pixel size valid untuk strike bitmap Noto Color Emoji (CBDT).
EMOJI_RENDER_SIZE = 109

# Range karakter yang dianggap emoji / simbol yang harus dirender warna.
def is_emoji_char(ch: str) -> bool:
    cp = ord(ch)
    if 0x1F000 <= cp <= 0x1FFFF:   # emoji & pictographs (termasuk 🇯 flag regional)
        return True
    if 0x2600 <= cp <= 0x27BF:     # misc symbols & dingbats (☀ ☂ ✌ dsb)
        return True
    if 0x2B00 <= cp <= 0x2BFF:     # misc symbols & arrows (⬛ dsb)
        return True
    if cp in (0x00A9, 0x00AE, 0x2122):  # © ® ™
        return True
    if cp in (0xFE0F, 0xFE0E):     # variation selectors (warna / teks)
        return True
    if cp == 0x200D:               # Zero Width Joiner (rasi emoji)
        return True
    if 0x1F3FB <= cp <= 0x1F3FF:   # skin tone modifiers
        return True
    if cp == 0x20E3:               # combining enclosing keycap
        return True
    return False


def split_runs(text: str):
    """Pecah teks jadi list (is_emoji, substring) berurutan."""
    if not text:
        return []
    runs = []
    cur = text[0]
    cur_emoji = is_emoji_char(text[0])
    for ch in text[1:]:
        e = is_emoji_char(ch)
        if e == cur_emoji:
            cur += ch
        else:
            runs.append((cur_emoji, cur))
            cur = ch
            cur_emoji = e
    runs.append((cur_emoji, cur))
    return runs


class FontCache:
    """Cache ImageFont supaya tidak load ulang per klip."""
    def __init__(self, base_font_path: str, emoji_font_path: str):
        self.base_font_path = base_font_path
        self.emoji_font_path = emoji_font_path

    def base(self, size: int):
        return ImageFont.truetype(self.base_font_path, size)

    def emoji(self, size: int):
        # emoji font bitmap hanya punya strike 109; gunakan embedded_color saat draw.
        return ImageFont.truetype(self.emoji_font_path, size)


def render_text_block(
    text: str,
    size: int,
    fill=(255, 255, 0, 255),
    stroke_width: int = 10,
    stroke_fill=(60, 51, 0, 255),
    line_spacing: int = -28,
    base_font_path: str = "./DynaPuff/DynaPuff-Medium.ttf",
    emoji_font_path: str = "./fonts/NotoColorEmoji.ttf",
):
    """Render blok teks (bisa multi-line '\n') jadi gambar RGBA transparan.

    Mengembalikan (PIL.Image, width_px, height_px) dalam ukuran tampilan target
    (`size`). Strok hanya diterapkan ke run teks biasa; emoji warna tidak
    distrok agar glyph bitmap warnanya tidak rusak.
    """
    R = EMOJI_RENDER_SIZE  # ukuran render (109)
    # faktor downscale dari render (109px) ke ukuran tampilan target (`size`).
    scale = float(size) / R if size > 0 else 1.0
    # faktor upscale nilai display (stroke, line_spacing) ke skala render.
    k = 1.0 / scale

    base_font = ImageFont.truetype(base_font_path, R)
    emoji_font = ImageFont.truetype(emoji_font_path, R)

    stroke_w = round(stroke_width * k)      # stroke dalam skala render
    line_spacing_r = line_spacing * k       # line_spacing dalam skala render

    lines = text.split("\n")

    # --- hitung ukuran tiap baris (pada skala render) ---
    line_metrics = []  # (width, height, [(run, run_w, run_h)])
    for line in lines:
        runs = split_runs(line)
        parts = []
        total_w = 0
        max_h = 0
        for is_emoji, sub in runs:
            font = emoji_font if is_emoji else base_font
            w = font.getlength(sub)
            stroke = 0 if is_emoji else stroke_w
            # ukuran header emoji ~ emoji box; teks biasa pake bbox + stroke
            if is_emoji:
                bbox = font.getbbox(sub)
                h = bbox[3] - bbox[1]
            else:
                bbox = font.getbbox(sub, stroke_width=stroke)
                h = bbox[3] - bbox[1]
            total_w += w + (stroke * 2 if not is_emoji else 0)
            max_h = max(max_h, h)
            parts.append((is_emoji, sub, w))
        line_metrics.append((total_w, max_h, parts))

    # --- tentukan line height konsisten ---
    # emoji bitmap ~ EMOJI_RENDER_SIZE tinggi; beri sedikit ruang.
    line_h = max(m[1] for m in line_metrics) if line_metrics else R
    line_h = max(line_h, R)
    line_step = line_h + line_spacing_r  # di skala render

    block_w = max(m[0] for m in line_metrics) if line_metrics else 1
    block_h = line_step * len(line_metrics) - line_spacing_r

    # padding buat strok biar tidak terpotong
    pad = max(stroke_w, 4) + 2
    block_w += pad * 2
    block_h += pad * 2

    canvas = Image.new("RGBA", (int(block_w), int(block_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    y = pad  # top
    for (line_w, _, parts) in line_metrics:
        x = pad + (block_w - 2 * pad - line_w) / 2  # center horizontal
        for is_emoji, sub, w in parts:
            font = emoji_font if is_emoji else base_font
            if is_emoji:
                draw.text((x, y), sub, font=font, embedded_color=True)
            else:
                draw.text(
                    (x, y),
                    sub,
                    font=font,
                    fill=fill,
                    stroke_width=stroke_w,
                    stroke_fill=stroke_fill,
                )
            x += w + (stroke_w * 2 if not is_emoji else 0)
        y += line_step

    # downscale ke ukuran tampilan target
    out_w = max(1, int(round(block_w * scale)))
    out_h = max(1, int(round(block_h * scale)))
    if (out_w, out_h) != canvas.size:
        canvas = canvas.resize((out_w, out_h), Image.LANCZOS)

    return canvas, canvas.width, canvas.height


if __name__ == "__main__":
    import sys

    txt = sys.argv[1] if len(sys.argv) > 1 else "Hello \U0001F602 test \U0001F525 halo"
    sz = int(sys.argv[2]) if len(sys.argv) > 2 else 64
    img, w, h = render_text_block(txt, sz)
    out = r"C:\Users\ACERNI~1\AppData\Local\Temp\opencode\render_text_out.png"
    img.save(out)
    print(f"text={txt!r} size={sz} -> {w}x{h} saved to {out}")
