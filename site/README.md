# Raven Landing Site

Scroll-animated landing site with video-driven frame animation.

## Structure

```
site/
├── index.html              # Main page with scroll sections
├── styles.css              # CRT terminal aesthetic
├── scroll-animation.js     # Scroll-driven frame renderer
├── frames/                 # Video frames (frame_0000.jpg, frame_0001.jpg, ...)
└── scripts/
    ├── extract_frames.py   # FFmpeg frame extraction
    └── generate_video_prompt.md  # Seedance video generation prompt
```

## How It Works

1. **Video Generation**: Use Seedance 2.0/2.5 (ByteDance) to generate a 20-30 second video of a camera flight through RAG architecture
2. **Frame Extraction**: Run `python site/scripts/extract_frames.py <video.mp4> site/frames 10` to extract frames at 10 FPS
3. **Scroll Animation**: JavaScript renders frames based on scroll position — scrolling through the page plays the video

## Current State

The site is functional but uses a **placeholder animation** (wireframe grid + text) until video frames are generated. Once you add frames to `site/frames/`, they'll automatically be used.

## Generate Video Frames

### Option 1: Seedance via Replicate
```bash
# Install replicate CLI or use Python SDK
pip install replicate

# Generate video (see scripts/generate_video_prompt.md for prompt)
# Download the video, then extract frames:
python site/scripts/extract_frames.py raven_intro.mp4 site/frames 10
```

### Option 2: Seedance via OpenRouter
```bash
# Use OpenRouter API
# See: https://openrouter.ai/bytedance/seedance-2.5
```

### Option 3: Create Your Own
Any continuous camera movement video works. Edit `scripts/generate_video_prompt.md` for the Raven-specific concept.

## Frame Requirements

- **Format**: JPEG
- **Naming**: `frame_0000.jpg`, `frame_0001.jpg`, `frame_0002.jpg`, ...
- **Resolution**: 1920x1080 recommended (will be scaled to fit viewport)
- **Count**: 200-300 frames for smooth animation (10 FPS × 20-30 seconds)

## Local Development

```bash
cd site
python -m http.server 8000
# Open http://localhost:8000
```

## Deployment

Automatic via GitHub Actions when changes are pushed to `site/**` on main branch.

Site URL: `https://ssrjkk.github.io/raven/`

## Customization

### Adjust Scroll Speed
Edit `data-scroll-start` and `data-scroll-end` attributes in `index.html` sections.

### Change Frame Rate
```bash
python site/scripts/extract_frames.py video.mp4 frames 15  # 15 FPS instead of 10
```

### Modify Visual Style
Edit `styles.css` — colors, fonts, transitions are all there.

## Fallback Animation

If no frames are found, the canvas displays a wireframe grid with "RAVEN MCP SERVER" text. This is intentional — the site works even without video generation.

## Performance

- Frames are loaded on init (all 300 images)
- Only the current frame is rendered to canvas
- Scroll listener is passive for smooth scrolling
- Total size: ~15-30 MB for 300 frames (optimize with TinyPNG if needed)

## Browser Support

- Chrome/Edge: Full support
- Firefox: Full support
- Safari: Full support
- Mobile: Works, but consider reducing frame count for slower connections
