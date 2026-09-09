#!/usr/bin/env python3
"""
program-single-clip.py

Render satu video pendek (single clip) ke format 1080x1920 (portrait) dengan
gaya sama seperti program-clipper.py:
  - Latar berupa animasi scrolling dari art/background-pattern.png
  - Teks judul (title) kuning dengan border, mirip clipper
  - art/video-overlay.png di-composite di atas frame (menutup seluruh canvas)

Perbedaan utama dari clipper:
  - Tidak pakai JSON / clips. Hanya menerima --video dan --title.
  - Seluruh durasi video dipakai (tanpa potongan).
  - Mode penyesuaian video bersifat dinamis berdasarkan aspect ratio sumber:
      * Landscape  (lebar > tinggi)  -> CONTAIN : seluruh video masuk ke canvas,
        sisi kosong diisi latar animasi, judul di atas frame video.
      * Portrait/square (lebar <= tinggi) -> COVER : video di-zoom+crop memenuhi
        seluruh canvas 1080x1920, judul di-overlay di atas video (y tetap).

Requirement: ffmpeg & ffprobe harus terinstall dan ada di PATH.

Contoh pakai:
    python program-single-clip.py \
        --video "Ballpool.mp4" \
        --title "Best Moments" \
        --output "single.mp4"

Opsional:
    --font /path/to/font.ttf   -> font custom untuk teks (default DynaPuff)
    --keep-temp                -> tidak menghapus folder kerja sementara (buat debug)

Catatan:
    Judul dirender ke PNG transparan via Pillow (lihat render_text.py) sehingga
    emoji berwarna didukung (font ./fonts/NotoColorEmoji.ttf).
    Pillow & Noto Color Emoji wajib ada.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import uuid

from render_text import render_text_block

# -----------------------------
# Konfigurasi output
# -----------------------------
OUT_W, OUT_H = 1080, 1920      # canvas akhir (portrait 9:16)

DEFAULT_FONT_CANDIDATES = ["./DynaPuff/DynaPuff-Medium.ttf"]

EMOJI_FONT_PATH = "./fonts/NotoColorEmoji.ttf"

TITLE_COLOR = (255, 255, 0, 255)
TITLE_BORDER = (60, 51, 0, 255)

TITLE_FONTSIZE = 64
TITLE_WRAP_CHARS = 26
TITLE_LINE_SPACING = -0       # rapatkan jarak antar baris
TEXT_MARGIN = 28               # jarak teks ke tepi frame video (mode contain)
COVER_TITLE_Y = 60             # posisi judul tetap (mode cover, di atas video)

VIDEO_BACKGROUND_PATTERN = "./art/background-pattern.png"
VIDEO_OVERLAY_IMAGE = "./art/video-overlay.png"


def find_font(user_font: str | None) -> str:
    if user_font:
        if not os.path.isfile(user_font):
            sys.exit(f"[ERROR] Font tidak ditemukan: {user_font}")
        return user_font
    for candidate in DEFAULT_FONT_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    sys.exit(
        "[ERROR] Tidak menemukan font default. "
        "Silakan tentukan lokasi font manual dengan --font /path/to/font.ttf"
    )


def get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Ambil width & height video sumber lewat ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        video_path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        sys.exit(f"[ERROR] Gagal membaca info video via ffprobe:\n{proc.stderr}")
    info = json.loads(proc.stdout)
    stream = info["streams"][0]
    return int(stream["width"]), int(stream["height"])


def get_video_duration(video_path: str) -> float:
    """Ambil durasi total video sumber (detik) lewat ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        sys.exit(f"[ERROR] Gagal membaca durasi video via ffprobe:\n{proc.stderr}")
    info = json.loads(proc.stdout)
    duration = float(info["format"]["duration"])
    if duration <= 0:
        sys.exit("[ERROR] Durasi video tidak valid (<= 0).")
    return duration


def compute_top_edge(src_w: int, src_h: int) -> float:
    """
    Hitung y tepi atas video setelah di-contain ke canvas OUT_W x OUT_H
    (hanya dipakai untuk mode contain/landscape).
    """
    scale_factor = min(OUT_W / src_w, OUT_H / src_h)
    scaled_h = src_h * scale_factor
    return (OUT_H - scaled_h) / 2


def run_ffmpeg(cmd: list[str]):
    """Jalankan perintah ffmpeg, tampilkan error kalau gagal."""
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        print("[FFMPEG ERROR]")
        print(" ".join(cmd))
        print(proc.stderr[-4000:])
        sys.exit(1)
    return proc


def wrap_text(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width)) or ""


def write_title_png(tmp_dir: str, text: str, font_path: str) -> tuple[str, int, int]:
    """Render judul jadi PNG transparan (mendukung emoji warna)."""
    wrapped = wrap_text(text, TITLE_WRAP_CHARS)
    img, w, h = render_text_block(
        wrapped,
        size=TITLE_FONTSIZE,
        fill=TITLE_COLOR,
        stroke_width=10,
        stroke_fill=TITLE_BORDER,
        line_spacing=TITLE_LINE_SPACING,
        base_font_path=font_path,
        emoji_font_path=EMOJI_FONT_PATH,
    )
    path = os.path.join(tmp_dir, f"title_{uuid.uuid4().hex}.png")
    img.save(path)
    return path, w, h


def build_video_background(image_path: str, duration: float, output_path: str = "output.mp4", speed: float = 6.0) -> None:
    """Membuat video latar dari gambar tiling yang bergerak ke kanan bawah (sama seperti clipper)."""
    grid_path = output_path + ".grid.png"
    tile_px = 200
    cols, rows = 10, 11               # grid 2000x2100
    try:
        run_ffmpeg([
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-vf", f"scale={tile_px}:{tile_px},tile={cols}x{rows}",
            "-frames:v", "1",
            "-c:v", "png",
            grid_path,
        ])

        max_span_x = cols * tile_px - OUT_W      # 920
        max_span_y = rows * tile_px - OUT_H      # 180
        span_x = min(tile_px, max_span_x)        # 100
        span_y = min(tile_px, max_span_y)        # 100

        crop_vf = (
            f"crop={OUT_W}:{OUT_H}:"
            f"x='mod(t*{speed},{span_x})':"
            f"y='mod(t*{speed},{span_y})',"
            f"format=yuv420p"
        )
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", "30", "-i", grid_path,
            "-vf", crop_vf,
            "-t", str(duration),
            "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path,
        ]
        run_ffmpeg(cmd)
        print(f"[INFO] Background video dibuat: {output_path} ({duration:.2f}s)")
    finally:
        if os.path.isfile(grid_path):
            os.remove(grid_path)


def build_filter_complex(mode: str, title_png: str, title_y: float) -> str:
    """
    Filter chain untuk satu clip (4 input video):
      input 0 = background video animasi (scrolling pattern)
      input 1 = source video (seluruh durasi, tanpa potongan)
      input 2 = art/video-overlay.png
      input 3 = PNG judul (sudah termasuk emoji warna)

    Mode:
      - "contain" (landscape, w > h): video di-scale contain penuh (decrease),
        di tengah, judul menempel tepat di atas tepi atas video.
      - "cover" (portrait/square, w <= h): video di-scale increase + crop memenuhi
        seluruh canvas 1080x1920, judul di-overlay di atas video pada y tetap.
    """
    if mode == "contain":
        video_scale = (
            f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease[vv]"
        )
    else:  # cover
        video_scale = (
            f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{OUT_H}[vv]"
        )

    filters = [
        f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H}[bg]",
        f"[1:v]{video_scale}",
        (
            f"[2:v]"
            f"scale={OUT_W}:{OUT_H}"
            f"[img_overlay]"
        ),
        f"[bg][vv]overlay=(W-w)/2:(H-h)/2[comp]",
        (
            f"[comp][3:v]overlay=(W-w)/2:{title_y:.2f}[comp2]"
        ),
        (
            f"[comp2][img_overlay]"
            f"overlay=0:0"
            f"[vout]"
        ),
    ]
    return ";".join(filters)


def get_has_audio(video_path: str) -> bool:
    """Cek apakah video sumber punya stream audio."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "json",
        video_path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return False
    info = json.loads(proc.stdout)
    return bool(info.get("streams"))


def process_single_clip(video_path: str, bg_path: str, mode: str, title_text: str, font_path: str, tmp_dir: str, top_edge_y: float, cover_title_y: float, duration: float) -> str:
    title_png, title_w, title_h = write_title_png(tmp_dir, title_text, font_path)

    if mode == "contain":
        title_y = top_edge_y - title_h - TEXT_MARGIN
    else:  # cover — posisi tetap
        title_y = cover_title_y

    out_path = os.path.join(tmp_dir, "single_clip.mp4")
    filter_complex = build_filter_complex(mode, title_png, title_y)

    cmd = [
        "ffmpeg", "-y",

        "-i", bg_path,

        "-i", video_path,

        "-loop", "1",
        "-i", VIDEO_OVERLAY_IMAGE,

        "-loop", "1", "-framerate", "30",
        "-i", title_png,

        "-t", str(duration),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
    ]

    if get_has_audio(video_path):
        cmd += [
            "-map", "1:a:0",
            "-c:a", "aac", "-b:a", "128k",
            "-ar", "44100", "-ac", "2",
        ]

    cmd += [out_path]

    print(f"[INFO] Memproses video (mode={mode}) -> {out_path}")
    run_ffmpeg(cmd)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Render satu video pendek 1080x1920 dengan judul (single clip).")
    parser.add_argument("--video", required=True, help="Path video sumber.")
    parser.add_argument("--title", required=True, help="Judul yang dirender di atas/bawah frame.")
    parser.add_argument("--output", default="output_single.mp4", help="Path file output final.")
    parser.add_argument("--font", default=None, help="Path font .ttf custom untuk teks.")
    parser.add_argument("--y", type=float, default=COVER_TITLE_Y, help="Koordinat Y judul untuk mode portrait/cover (default 60).")
    parser.add_argument("--keep-temp", action="store_true", help="Simpan folder temp (untuk debug).")
    args = parser.parse_args()

    if not os.path.isfile(args.video):
        sys.exit(f"[ERROR] Video tidak ditemukan: {args.video}")

    if not os.path.isfile(VIDEO_BACKGROUND_PATTERN):
        sys.exit(f"[ERROR] Background pattern tidak ditemukan: {VIDEO_BACKGROUND_PATTERN}")

    font_path = find_font(args.font)

    src_w, src_h = get_video_dimensions(args.video)
    duration = get_video_duration(args.video)

    if src_w > src_h:
        mode = "contain"
    else:
        mode = "cover"

    top_edge_y = compute_top_edge(src_w, src_h) if mode == "contain" else 0.0
    print(
        f"[INFO] Video sumber {src_w}x{src_h} ({duration:.2f}s) -> mode={mode} "
        f"(landscape=contain, portrait/square=cover)"
    )

    tmp_dir = tempfile.mkdtemp(prefix="single_clip_")
    print(f"[INFO] Folder kerja sementara: {tmp_dir}")

    try:
        bg_path = os.path.join(tmp_dir, "background.mp4")
        build_video_background(VIDEO_BACKGROUND_PATTERN, duration, bg_path)

        out_path = process_single_clip(
            args.video, bg_path, mode, args.title, font_path, tmp_dir, top_edge_y, args.y, duration,
        )

        shutil.move(out_path, args.output)
        print(f"[DONE] Video selesai dibuat: {args.output}")
    finally:
        if args.keep_temp:
            print(f"[INFO] Folder temp disimpan di: {tmp_dir}")
        else:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
