# Animal Clip Engine

**Auto clip & vertical render** - Transform long animal videos into engaging short clips for social media.

---

## Overview

The Animal Clip Engine is a comprehensive video processing system that creates vertical (9:16) animal content from long videos. It combines automated clip selection with custom overlays, text rendering, and emoji support to produce professional-looking short-form videos.

This tool is ideal for content creators who want to:
- Create highlight reels from longer animal videos
- Produce vertical videos for TikTok, Instagram Reels, YouTube Shorts
- Add stylish text overlays with emoji support
- Process videos through an easy-to-use web interface

---

## Quick Start

### Option 1: Using the Web Interface (Recommended)

1. Navigate to `http://localhost:8080`
2. Upload your video file
3. Create or paste your JSON configuration
4. Click "Process & Render"
5. Download your short clip when complete

### Option 2: Command Line Processing

```bash
# Multi-Clip Clipper - creates highlight reels from specific segments
python program-clipper.py --video "video.mp4" --json "clips.json" --output "short.mp4"

# Single Clip with title - applies overlay to entire video
python program-single-clip.py --video "video.mp4" --title "Best Moments" --output "single.mp4"

# Single Clip with JSON titles - multiple titles with time ranges
python program-single-clip.py --video "video.mp4" --json "titles.json" --output "single.mp4"
```

---

## Supported Formats

### Input Videos
- MP4, MOV, MKV, and other common formats
- Any duration supported

### JSON Configuration

**Multi-Clip Clipper** (`program-clipper.py`):
```json
{
  "title": "Video Title Here",
  "caption": "Optional caption",
  "hashtags": ["#tag1", "#tag2"],
  "clips": [
    {
      "start": 0.0,
      "end": 10.5,
      "text": "Clip description text"
    },
    {
      "start": 25.3,
      "end": 32.1,
      "text": "Another exciting moment"
    }
  ]
}
```

**Single Clip** (`program-single-clip.py`):
```json
{
  "titles": [
    {
      "text": "First title",
      "start": 0.0,
      "end": 10.0
    },
    {
      "text": "Second title appears later",
      "start": 15.0,
      "end": 25.0
    }
  ]
}
```

Note: For single clip with one title spanning the entire video, you can use `--title` instead of `--json`.

---

## File Structure

```
AnimalClipEngine/
├── program-clipper.py           # Multi-clip processing engine
├── program-single-clip.py        # Single-clip processing engine
├── server.go                    # HTTP server (Go)
├── index.html                   # Main landing page
├── clipper.html                 # Multi-clip web interface
├── single-clip.html             # Single-clip web interface
├── style.css                    # Web interface styling
├── output/                      # Generated video files
├── json/                        # Example JSON configurations
├── art/                         # Background and overlay assets
├── fonts/                       # Custom fonts
│   ├── DynaPuff-Medium.ttf
│   └── NotoColorEmoji.ttf
└── transcription/               # Transcribed video content for reference
```

---

## Processing Modes

### Multi-Clip Clipper (`program-clipper.py`)

**Purpose**: Cut specific segments from a video and combine them into one highlight reel.

**Output**: Vertical video (1080x1920) with multiple clips concatenated, each with:
- Scrolling animated background
- Original video clip centered (contain mode)
- Title overlay above video
- Subtitle overlay below video  
- Overlay graphic on top

**Use Case**: Creating highlight reels, best moments compilations, or summarized content from longer videos.

### Single Clip (`program-single-clip.py`)

**Purpose**: Process an entire video with dynamic overlays.

**Output**: Vertical video (1080x1920) with:
- Scrolling animated background
- Smart video handling based on aspect ratio
- Title overlays that appear at specified times

**Smart Mode Detection**:
- **Landscape (width > height)**: CONTAIN mode
  - Video scales to fit within canvas
  - Background fills empty space on sides/top/bottom
  - Titles positioned above video frame
- **Portrait/Square (width ≤ height)**: COVER mode
  - Video scales to fill entire frame
  - Titles overlay directly on video

**Use Case**: Processing complete videos with timed text annotations, adding titles to full clips.

---

## Video Features

### Background Animation
- Smooth scrolling pattern from `art/background-pattern.png`
- Diagonal movement (bottom-left to top-right)
- Seamless looping with no visible jumps
- Configurable speed (default: 6 pixels/second)

### Text Overlays
- **Multi-Clip Mode**:
  - Titles: Yellow text with dark border, above video
  - Subtitles: White text with dark border, below video
- **Single Clip Mode**:
  - Titles: Yellow text with dark border, positioned based on mode
- **Both Modes**:
  - Full emoji color support via Noto Color Emoji font
  - Automatic text wrapping
  - Stroke/border for readability on any background
  - Custom font support (defaults to DynaPuff)

### Video Composition
- Resolution: 1080x1920 (9:16 vertical)
- Frame rate: 30 FPS
- Video codec: H.264 (libx264)
- Audio codec: AAC (when present)
- Pixel format: yuv420p (broadcast compatible)
- Preset: veryfast (good speed/quality balance)
- CRF: 20 (good quality)

---

## System Requirements

### Software Dependencies

```bash
# Core tools (must be in PATH)
ffmpeg (with libx264, aac support)
ffprobe
python3 (version 3.8+ recommended)

# Python packages
pip install pillow
```

### Required Resources
These files must be present in the project directory:
- `art/background-pattern.png` - Background texture for scrolling animation
- `art/video-overlay.png` - Overlay graphic that appears on top
- `fonts/DynaPuff-Medium.ttf` - Main font for text overlays
- `fonts/NotoColorEmoji.ttf` - Emoji font for color emoji support

### Optional but Recommended
- Sufficient disk space for temporary files (approximately 2-3x video size)
- Internet connection for initial setup (not required for processing)

---

## Web Interface Usage

### Multi-Clip Clipper Page (`/clipper.html`)

1. **Upload Video**:
   - Drag and drop video file onto the designated area
   - Or click to browse and select a file
   - Supported formats: MP4, MOV, MKV, AVI, etc.
   - File name and size will be displayed after selection

2. **Configure Clips**:
   - Textarea pre-filled with example JSON
   - Use buttons for common actions:
     - 📋 **Sample**: Load example configuration
     - 🎨 **Pretty**: Format/indent current JSON
     - ✅ **Validate**: Check JSON structure and correctness
   - JSON must contain:
     - `title` (string): Main video title
     - `clips` (array): Objects with `start`, `end` (seconds), and `text`
     - Optional: `caption` (string), `hashtags` (array)

3. **Set Output**:
   - Enter desired output filename (default: `ringkasan.mp4`)
   - Will be saved as MP4 regardless of extension

4. **Process**:
   - Click "Proses & Render" button
   - Status shows progress: "Mengupload & merender..."
   - Processing time depends on video length and complexity
   - Logs show FFmpeg progress if needed

5. **Download**:
   - When complete, status shows "Selesai!"
   - Click "Download Video Hasil" to save the file
   - Link is valid for one download only

### Single Clip Page (`/single-clip.html`)

1. **Upload Video**:
   - Same process as multi-clip page
   - Entire video duration will be used (no cutting)

2. **Add Titles**:
   - Start with one title row
   - Click "+ Tambah Judul" to add more title rows
   - Each row requires:
     - Judul (text): The title to display
     - Mulai (s): Start time in seconds
     - Selesai (s): End time in seconds (leave empty for video duration)
   - Click × on any row to remove it

3. **Set Output & Position**:
   - Output filename (default: `single.mp4`)
   - Posisi Y judul: Vertical position for titles in cover mode (default: 60px from top)

4. **Process & Download**:
   - Same flow as multi-clip page

---

## API Endpoints

### Program-Clipper (`/api/clipper`)

Processes videos with multiple clips using JSON configuration.

**Method**: POST  
**Content-Type**: multipart/form-data

**Parameters**:
- `video` (file): Video file to process
- `json` (string): JSON configuration as described above
- `output` (string, optional): Desired output filename

**Response**:
- Success: Video file with appropriate headers for download
  - Content-Type: video/mp4
  - Content-Disposition: attachment; filename="[output]"
- Error: JSON error message
  - Content-Type: application/json
  - Body: {"error": "error description"}

### Single Clip (`/api/single-clip`)

Processes entire video with title overlays.

**Method**: POST  
**Content-Type**: multipart/form-data

**Parameters**:
- `video` (file): Video file to process
- `title` (string, optional): Single title for entire video
- `json` (string, optional): JSON with `titles` array for timed titles
- `output` (string, optional): Desired output filename
- `y` (number, optional): Y position for titles in cover mode (default: 60)

**Note**: Provide either `title` OR `json`, not both.

**Response**: Same as program-clipper endpoint.

---

## Example Videos

The project includes example configurations to get you started quickly.

### Running the Test Example

```bash
# Process the Ballpool video with the test JSON
python program-clipper.py --video "videos/Ballpool.mp4" --json "json/Test.json" --output "demo_highlight.mp4"

# Or use the single clip processor
python program-single-clip.py --video "videos/Ballpool.mp4" --json "json/Test.json" --output "demo_single.mp4"
```

### Available Examples

Check the `json/` folder for various example configurations:
- `Test.json` - Sample multi-clip configuration
- Other JSON files in transcription folder - derived from video transcriptions

The `transcription/` folder contains transcribed content from various animal videos that can be used as inspiration for creating your own JSON configurations.

---

## Configuration Options

### Font Customization

Use custom fonts for text overlays:

```bash
# Specify custom font file
python program-clipper.py --video video.mp4 --json clips.json --font "/path/to/custom/font.ttf"

# Works with both processors
python program-single-clip.py --video video.mp4 --title "Custom Font" --font "/path/to/font.ttf"
```

### Temporary Files

Keep intermediate files for debugging or inspection:

```bash
# Don't delete temporary working directory
python program-clipper.py --video video.mp4 --json clips.json --keep-temp
# Temp dir will be something like: /tmp/clip_summarizer_a1b2c3d4
```

### JSON Validation

All JSON inputs are automatically validated:
- Required fields must be present
- Time values must be numbers
- Start time must be >= 0
- End time must be > start time
- For single clip: either title or json (with titles array) must be provided

---

## Troubleshooting

### Common Issues

**"Font not found: ./DynaPuff/DynaPuff-Medium.ttf"**
- Solution: Ensure the DynaPuff folder is present with the font file
- Alternative: Use `--font` to specify a different .ttf file

**"Pillow module not found"**
- Solution: Install with `pip install pillow`

**"ffmpeg not found" or codec errors**
- Solution: Install ffmpeg with libx264 and aac support
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`
  - Windows: Download from https://ffmpeg.org/download.html

**"Video processing failed"**
- Check that input video is valid and not corrupted
- Ensure sufficient disk space for temporary files
- Verify that art/ and fonts/ folders contain required files
- Try with `--keep-temp` to inspect intermediate files

**"JSON validation failed"**
- Verify JSON syntax is correct
- Check that all required fields are present
- Ensure time values are numbers, not strings
- Make sure clips array is not empty

### Debug Mode

Run with `--keep-temp` to:
- Keep temporary files for inspection
- See intermediate background videos
- Examine individual clip outputs
- Locate the temp directory in the console output

---

## Getting Help

### Documentation

- [SKILLS.md](docs/SKILLS.md) - Guidelines for creating effective JSON configurations
- Transcribed videos in `transcription/` folder - reference for content ideas
- HTML files in root folder - frontend implementation details
- Python files - processing logic and algorithms

### Community and Support

For issues, questions, or contributions:
- Visit the project repository
- Check existing issues before submitting new ones
- Provide detailed information when reporting problems:
  - Command used or web interface actions
  - Error messages (exact text)
  - ffmpeg/console output if available
  - Video file properties (format, duration, resolution)
  - JSON configuration being used

### Related Projects

This engine is designed specifically for animal content creation but can be adapted for other vertical video needs.

---

## License

Font files are licensed under SIL Open Font License (OFL):
- See `fonts/OFL.txt` for details
- DynaPuff font: OFL license
- Noto Color Emoji font: OFL license

All other code and assets are available for use and modification.

---

*Animal Clip Engine - Transforming animal videos into engaging short-form content*

Built with ❤️ for animal lovers and content creators worldwide.