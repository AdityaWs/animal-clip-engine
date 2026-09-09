#!/usr/bin/env python3
"""
clip_summarizer.py

Prototype: potong video panjang jadi ringkasan pendek berdasarkan clips di JSON,
lalu render ulang tiap clip ke format 1080x1920 (portrait), dengan video asli
di-contain penuh (scale 1.0, tidak diperkecil) di tengah frame (letterbox hitam
kalau aspect ratio-nya beda), ditambah teks judul (title) tepat di atas frame
video dan teks/subtitle (per-clip) tepat di bawah frame video.

Semua clip hasil potongan digabung jadi satu file output akhir.

Requirement: ffmpeg & ffprobe harus terinstall dan ada di PATH.

Contoh pakai:
    python clip_summarizer.py \
        --video "Ballpool.mp4" \
        --json "Ballpool_Obstacle_Course_Challenge.json" \
        --output "ringkasan.mp4"

Opsional:
    --font /path/to/font.ttf   -> font custom untuk teks (default DynaPuff)
    --keep-temp                -> tidak menghapus folder kerja sementara (buat debug)

Catatan:
    Teks (judul & subtitle) dirender ke PNG transparan via Pillow (lihat
    render_text.py) sehingga emoji berwarna didukung (font ./fonts/NotoColorEmoji.ttf).
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
SCALE_RATIO = 1.0              # video asli di-contain penuh di canvas (tidak diperkecil lagi)
BOX_W = int(OUT_W * SCALE_RATIO)
BOX_H = int(OUT_H * SCALE_RATIO)

DEFAULT_FONT_CANDIDATES = ["./DynaPuff/DynaPuff-Medium.ttf"]

EMOJI_FONT_PATH = "./fonts/NotoColorEmoji.ttf"

TITLE_COLOR = (255, 255, 0, 255)
TITLE_BORDER = (60, 51, 0, 255)
SUB_COLOR = (255, 255, 255, 255)
SUB_BORDER = (49, 49, 49, 255)

TITLE_FONTSIZE = 64
SUB_FONTSIZE = 32
TITLE_WRAP_CHARS = 26
SUB_WRAP_CHARS = 36
TITLE_LINE_SPACING = -0        # rapatkan jarak antar baris (default font metric-nya cukup lebar)
LINE_SPACING = -0              # rapatkan jarak antar baris (default font metric-nya cukup lebar)
TEXT_MARGIN = 28               # jarak teks ke tepi frame video (atas untuk title, bawah untuk subtitle)

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


def compute_frame_edges(src_w: int, src_h: int) -> tuple[float, float, float, float]:
    """
    Hitung posisi tepi video asli setelah di-contain (scale + pad) ke canvas
    OUT_W x OUT_H. Mengembalikan (scaled_w, scaled_h, top_edge_y, bottom_edge_y).
    """
    scale_factor = min(BOX_W / src_w, BOX_H / src_h)
    scaled_w = src_w * scale_factor
    scaled_h = src_h * scale_factor

    top_edge_y = (OUT_H - scaled_h) / 2
    bottom_edge_y = top_edge_y + scaled_h
    return scaled_w, scaled_h, top_edge_y, bottom_edge_y


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


def write_text_png(tmp_dir: str, prefix: str, text: str, size: int, color, border, wrap_chars: int, font_path: str) -> tuple[str, int, int]:
    """Render blok teks jadi PNG transparan (mendukung emoji warna).

    Mengembalikan (path_png, width_px, height_px) dalam ukuran tampilan.
    """
    wrapped = wrap_text(text, wrap_chars)
    img, w, h = render_text_block(
        wrapped,
        size=size,
        fill=color,
        stroke_width=10,
        stroke_fill=border,
        line_spacing=TITLE_LINE_SPACING if prefix == "title" else LINE_SPACING,
        base_font_path=font_path,
        emoji_font_path=EMOJI_FONT_PATH,
    )
    path = os.path.join(tmp_dir, f"{prefix}_{uuid.uuid4().hex}.png")
    img.save(path)
    return path, w, h


def build_video_background(image_path: str, duration: float, output_path: str = "output.mp4", speed: float = 6.0) -> None:
    """Membuat video latar dari gambar tiling yang bergerak ke kanan bawah.

    Dilakukan 2 tahap karena filter `tile` butuh buffering ratusan frame sebelum
    mengeluarkan frame hasil tile (tidak cocok dipakai langsung dgn scroll/animasi):

      1. Pattern di-scale ke 100x100 lalu di-tile jadi grid besar
         (20 kolom x 21 baris -> 2000x2100), disimpan sementara sbg PNG tunggal.
      2. Grid di-loop jadi video, lalu jendela crop 1080x1920 digeser diagonal
         (kanan-bawah) dgn kecepatan `speed` px/detik. Gesernya dibatasi persis
         100px (1 tile), jadi saat `mod` wrap ke awal tidak terlihat sambungannya
         (seamless) karena pattern periodik per 100px.

    :param image_path: Path ke file gambar (PNG/JPG).
    :param duration: Durasi video output dalam detik.
    :param output_path: Path file video hasil generator.
    :param speed: Kecepatan gerakan scroll dalam pixels per detik (default: 6).
    """
    grid_path = output_path + ".grid.png"
    tile_px = 200
    cols, rows = 10, 11               # grid 2000x2100 (cukup tinggi utk sweep 1920 + 1 tile)
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
        span_x = min(tile_px, max_span_x)        # 100 (1 tile = aman saat wrap)
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


def build_filter_complex(title_png: str, sub_png: str, title_y: float, sub_y: float) -> str:
    """
    Filter chain per clip (5 input video):
      input 0 = background video animasi (scrolling pattern)
      input 1 = source clip
      input 2 = art/video-overlay.png (menutup seluruh canvas)
      input 3 = PNG judul (sudah termasuk emoji warna)
      input 4 = PNG subtitle (sudah termasuk emoji warna)

      1. [0:v] background di-crop ke canvas OUT_W x OUT_H penuh
      2. [1:v] video asli di-scale (contain penuh, jaga aspect ratio)
      3. Overlay video asli di tengah background
      4. Overlay PNG judul di tengah horizontal, y = title_y (di atas tepi video)
      5. Overlay PNG subtitle di tengah horizontal, y = sub_y (di bawah tepi video)
      6. Overlay video-overlay.png di atas semuanya
    """
    filters = [
        f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H}[bg]",
        f"[1:v]scale={BOX_W}:{BOX_H}:force_original_aspect_ratio=decrease[vv]",
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
            f"[comp2][4:v]overlay=(W-w)/2:{sub_y:.2f}[comp3]"
        ),
        (
            f"[comp3][img_overlay]"
            f"overlay=0:0"
            f"[vout]"
        ),
    ]
    return ";".join(filters)


def process_clip(video_path: str, bg_path: str, bg_start: float, clip: dict, title_text: str, font_path: str, tmp_dir: str, index: int, top_edge_y: float, bottom_edge_y: float) -> str:
    start = float(clip["start"])
    end = float(clip["end"])
    duration = round(end - start, 3)
    if duration <= 0:
        raise ValueError(f"Clip #{index} punya durasi tidak valid: start={start} end={end}")

    subtitle_text = clip.get("text", "")

    title_png, title_w, title_h = write_text_png(
        tmp_dir, "title", title_text, TITLE_FONTSIZE,
        TITLE_COLOR, TITLE_BORDER, TITLE_WRAP_CHARS, font_path,
    )
    sub_png, sub_w, sub_h = write_text_png(
        tmp_dir, "sub", subtitle_text, SUB_FONTSIZE,
        SUB_COLOR, SUB_BORDER, SUB_WRAP_CHARS, font_path,
    )

    title_y = top_edge_y - title_h - TEXT_MARGIN
    sub_y = bottom_edge_y + TEXT_MARGIN

    out_path = os.path.join(tmp_dir, f"clip_{index:03d}.mp4")
    filter_complex = build_filter_complex(title_png, sub_png, title_y, sub_y)

    cmd = [
        "ffmpeg", "-y",

        "-ss", str(bg_start),       # seek background sesuai offset global (scroll kontinu)
        "-i", bg_path,

        "-ss", str(start),          # fast seek sebelum -i (cepat, cukup akurat untuk prototype)
        "-i", video_path,

        "-loop", "1",
        "-i", VIDEO_OVERLAY_IMAGE,

        "-loop", "1", "-framerate", "30",
        "-i", title_png,

        "-loop", "1", "-framerate", "30",
        "-i", sub_png,

        "-t", str(duration),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "1:a:0",
        "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-ar", "44100", "-ac", "2",
        out_path,
    ]
    print(f"[INFO] Memproses clip #{index}: {start}s - {end}s ({duration}s) -> {out_path}")
    run_ffmpeg(cmd)
    return out_path


def concat_clips(clip_paths: list[str], tmp_dir: str, output_path: str):
    list_file = os.path.join(tmp_dir, "concat_list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            abs_p = os.path.abspath(p).replace("'", "'\\''")
            f.write(f"file '{abs_p}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output_path,
    ]
    print(f"[INFO] Menggabungkan {len(clip_paths)} clip -> {output_path}")
    run_ffmpeg(cmd)


def main():
    parser = argparse.ArgumentParser(description="Ringkas video panjang jadi video pendek berdasarkan JSON clips.")
    parser.add_argument("--video", required=True, help="Path video sumber (panjang).")
    parser.add_argument("--json", required=True, help="Path file JSON berisi title & clips.")
    parser.add_argument("--output", default="output_ringkasan.mp4", help="Path file output final.")
    parser.add_argument("--font", default=None, help="Path font .ttf custom untuk teks overlay.")
    parser.add_argument("--keep-temp", action="store_true", help="Simpan folder temp (untuk debug).")
    args = parser.parse_args()

    if not os.path.isfile(args.video):
        sys.exit(f"[ERROR] Video tidak ditemukan: {args.video}")
    if not os.path.isfile(args.json):
        sys.exit(f"[ERROR] JSON tidak ditemukan: {args.json}")

    with open(args.json, "r", encoding="utf-8") as f:
        data = json.load(f)

    title_text = data.get("title", "")
    clips = data.get("clips", [])
    if not clips:
        sys.exit("[ERROR] JSON tidak punya field 'clips' atau kosong.")

    if not os.path.isfile(VIDEO_BACKGROUND_PATTERN):
        sys.exit(f"[ERROR] Background pattern tidak ditemukan: {VIDEO_BACKGROUND_PATTERN}")

    font_path = find_font(args.font)

    src_w, src_h = get_video_dimensions(args.video)
    scaled_w, scaled_h, top_edge_y, bottom_edge_y = compute_frame_edges(src_w, src_h)
    print(
        f"[INFO] Video sumber {src_w}x{src_h} -> di-contain jadi {scaled_w:.0f}x{scaled_h:.0f} "
        f"di dalam canvas {OUT_W}x{OUT_H} (tepi atas y={top_edge_y:.0f}, tepi bawah y={bottom_edge_y:.0f})"
    )

    tmp_dir = tempfile.mkdtemp(prefix="clip_summarizer_")
    print(f"[INFO] Folder kerja sementara: {tmp_dir}")

    try:
        clip_offsets = []
        acc = 0.0
        for clip in clips:
            clip_offsets.append(acc)
            acc += round(float(clip["end"]) - float(clip["start"]), 3)
        total_duration = acc

        bg_path = os.path.join(tmp_dir, "background.mp4")
        build_video_background(VIDEO_BACKGROUND_PATTERN, total_duration, bg_path)

        processed_paths = []
        for i, clip in enumerate(clips, start=1):
            out_clip = process_clip(
                args.video, bg_path, clip_offsets[i - 1], clip, title_text, font_path, tmp_dir, i,
                top_edge_y, bottom_edge_y,
            )
            processed_paths.append(out_clip)

        concat_clips(processed_paths, tmp_dir, args.output)
        print(f"[DONE] Video ringkasan berhasil dibuat: {args.output}")
    finally:
        if args.keep_temp:
            print(f"[INFO] Folder temp disimpan di: {tmp_dir}")
        else:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()