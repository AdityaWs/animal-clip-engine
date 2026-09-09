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
    --font /path/to/font.ttf   -> font custom untuk drawtext (default DejaVu Sans Bold)
    --keep-temp                -> tidak menghapus folder kerja sementara (buat debug)
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

# -----------------------------
# Konfigurasi output
# -----------------------------
OUT_W, OUT_H = 1080, 1920      # canvas akhir (portrait 9:16)
SCALE_RATIO = 1.0              # video asli di-contain penuh di canvas (tidak diperkecil lagi)
BOX_W = int(OUT_W * SCALE_RATIO)
BOX_H = int(OUT_H * SCALE_RATIO)

DEFAULT_FONT_CANDIDATES = ["./DynaPuff/DynaPuff-Medium.ttf"]

TITLE_FONTSIZE = 64
SUB_FONTSIZE = 32
TITLE_WRAP_CHARS = 26
SUB_WRAP_CHARS = 36
TITLE_LINE_SPACING = -28       # rapatkan jarak antar baris (default font metric-nya cukup lebar)
LINE_SPACING = -10             # rapatkan jarak antar baris (default font metric-nya cukup lebar)
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


def clean_text_for_overlay(text: str) -> str:
    """
    Buang emoji/karakter non-BMP yang biasanya tidak punya glyph di font default
    (DejaVu dkk), supaya drawtext tidak menampilkan kotak-kotak aneh.
    Karakter Indonesia standar (huruf latin, tanda baca umum) tetap aman.
    """
    cleaned = []
    for ch in text:
        cp = ord(ch)
        if 0x1F000 <= cp <= 0x1FFFF or 0x2600 <= cp <= 0x27BF or cp == 0xFE0F:
            continue
        cleaned.append(ch)
    return "".join(cleaned).strip()


def wrap_text(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width)) or ""


def write_textfile(tmp_dir: str, prefix: str, text: str) -> str:
    """
    ffmpeg drawtext lebih aman baca teks dari file (textfile=...) daripada
    inline text=..., karena kita tidak perlu escape karakter spesial (':', ''', dst).
    """
    path = os.path.join(tmp_dir, f"{prefix}_{uuid.uuid4().hex}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


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


def build_filter_complex(title_file: str, sub_file: str, font_path: str, top_edge_y: float, bottom_edge_y: float) -> str:
    """
    Filter chain per clip (2 input video):
      input 0 = background video animasi (scrolling pattern), input 1 = source clip

      1. [0:v] background di-crop ke canvas OUT_W x OUT_H penuh
      2. [1:v] video asli di-scale (contain penuh, jaga aspect ratio)
      3. Overlay video asli di tengah background -> letterbox hitam tergantikan
         oleh background animasi
      4. Drawtext judul, diletakkan tepat menempel di atas tepi video (top_edge_y)
      5. Drawtext subtitle, diletakkan tepat menempel di bawah tepi video (bottom_edge_y)

    Posisi video asli setelah overlay = (w-ow)/2 : (h-oh)/2, sama persis dengan pad
    center dulu, jadi top_edge_y / bottom_edge_y dari compute_frame_edges tetap valid.

    Title & subtitle di-center secara horizontal (x=(w-text_w)/2) DAN tiap baris teks
    di dalam blok multi-line-nya juga di-center (text_align=center) -- tanpa
    text_align, ffmpeg hanya me-rata-kiri-kan baris yang lebih pendek di dalam blok.
    """
    
    def esc(p: str) -> str:
        return p.replace("\\", "/").replace(":", "\\:")

    font_esc = esc(font_path)
    title_esc = esc(title_file)
    sub_esc = esc(sub_file)

    title_y_expr = f"{top_edge_y:.2f}-text_h-{TEXT_MARGIN}"
    sub_y_expr = f"{bottom_edge_y:.2f}+{TEXT_MARGIN}"

    common = (
        f"fontsize={{size}}:"
        f"text_align=center:"
        f"x=(w-text_w)/2"
    )

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
            f"[comp]drawtext=fontfile='{font_esc}':textfile='{title_esc}':bordercolor=#3C3300:borderw=10:fontcolor=#FFFF00:line_spacing={TITLE_LINE_SPACING}:"
            + common.format(size=TITLE_FONTSIZE)
            + f":y={title_y_expr}[comp2]"
        ),
        (
            f"[comp2]drawtext=fontfile='{font_esc}':textfile='{sub_esc}':bordercolor=#313131:borderw=10:fontcolor=white:line_spacing={LINE_SPACING}:"
            + common.format(size=SUB_FONTSIZE)
            + f":y={sub_y_expr}[img_src]"
        ),
        (
            f"[img_src][img_overlay]"
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

    raw_text = clip.get("text", "")
    subtitle_text = clean_text_for_overlay(raw_text)
    title_clean = clean_text_for_overlay(title_text)

    title_wrapped = wrap_text(title_clean, TITLE_WRAP_CHARS)
    sub_wrapped = wrap_text(subtitle_text, SUB_WRAP_CHARS)

    title_file = write_textfile(tmp_dir, "title", title_wrapped)
    sub_file = write_textfile(tmp_dir, "sub", sub_wrapped)

    out_path = os.path.join(tmp_dir, f"clip_{index:03d}.mp4")
    filter_complex = build_filter_complex(title_file, sub_file, font_path, top_edge_y, bottom_edge_y)

    cmd = [
        "ffmpeg", "-y",

        "-ss", str(bg_start),       # seek background sesuai offset global (scroll kontinu)
        "-i", bg_path,

        "-ss", str(start),          # fast seek sebelum -i (cepat, cukup akurat untuk prototype)
        "-i", video_path,

        "-loop", "1",
        "-i", VIDEO_OVERLAY_IMAGE,

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