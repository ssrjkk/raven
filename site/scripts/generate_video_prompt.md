# Seedance Video Generation Prompt for Raven Landing Site

## Concept
Continuous camera flight through digital RAG (Retrieval-Augmented Generation) architecture, visualizing data flow from query to response.

## Visual Style
- **Aesthetic**: Wireframe/PS1 low-poly, CRT terminal glow
- **Color Palette**: Dark background (#0a0a0a), neon green (#00ff41), cyan accents (#00ffff)
- **Mood**: Cyberpunk, technical, futuristic but retro

## Scene Progression (15-30 seconds)

### 0-5s: Server Structure
Camera approaches a massive server rack made of glowing wireframe cubes. Data streams (particle effects) flow between nodes. Low-poly geometry with visible edges.

### 5-10s: Depth Map / Thermal Vision
Camera dives into the server structure. View shifts to thermal/depth map visualization — hot zones (bright green/yellow) show active processing, cool zones (dark blue) show idle nodes. Wireframe overlay persists.

### 10-15s: Data Retrieval
Camera follows a data packet through a retrieval pipeline. ASCII-style text scrolls past (simulated RAG context). CRT scanline effect intensifies.

### 15-20s: LLM Processing
Camera enters a "neural chamber" — low-poly brain-like structure with pulsing connections. Glowing nodes represent transformer layers. Text fragments float and recombine.

### 20-25s: Response Generation
Camera pulls back as response text materializes in mid-air (wireframe letters assembling). CRT terminal aesthetic peaks — green text on black, scanlines, slight glow.

### 25-30s: Final Pullback
Camera retreats to show the entire architecture as a unified system. All data flows converge. Fade to Raven logo (wireframe).

## Technical Specs
- **Resolution**: 1920x1080 (16:9)
- **Duration**: 20-25 seconds
- **FPS**: 30 (will be sampled to 10 FPS for web)
- **Style**: Consistent wireframe/low-poly throughout, no photorealism

## Seedance Prompt (English)
```
Continuous first-person camera flight through cyberpunk RAG architecture. Low-poly wireframe aesthetic, PS1 retro style. Dark background with neon green (#00ff41) and cyan glowing edges. 

Scene 1: Approach massive wireframe server rack, data streams flowing between nodes.
Scene 2: Dive inside, thermal vision view — hot zones bright green, cool zones dark blue.
Scene 3: Follow data packet through retrieval pipeline, ASCII text scrolling past.
Scene 4: Enter neural chamber, low-poly brain structure with pulsing transformer layers.
Scene 5: Response text materializes in mid-air, CRT terminal aesthetic with scanlines.
Scene 6: Pull back to show unified system, fade to wireframe logo.

CRT monitor glow, scanline effect, cyberpunk atmosphere, technical visualization. Smooth continuous camera movement, no cuts.
```

## Seedance Prompt (Alternative — Shorter)
```
First-person flight through wireframe RAG architecture. Low-poly PS1 style, neon green on black. Server racks → thermal depth map → ASCII data streams → neural network chamber → text materialization → system overview. CRT glow, scanlines, continuous camera, 20 seconds.
```

## Generation Options
- **Replicate**: `bytedance/seedance-2.0` — ~$0.50-1.00 per generation
- **OpenRouter**: `bytedance/seedance-2.5` — check current pricing
- **BytePlus ModelArk**: Official API, may have free tier

## Post-Processing
After generating video:
```bash
python site/scripts/extract_frames.py <video.mp4> site/frames 10
```

This extracts frames at 10 FPS (300 frames for 30s video), optimized for smooth scroll animation.

## Fallback
If Seedance generation fails or is unavailable, create placeholder animation using:
- Three.js wireframe renderer
- CSS 3D transforms
- Canvas-based particle system

Current site includes canvas placeholder that displays grid + "RAVEN MCP SERVER" text.
