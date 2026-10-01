# Generate Landing Video

## Option 1: Procedural Animation (No API Required)

The site now includes a procedural canvas animation that works immediately without video generation. It features:
- Animated wireframe grid
- Glowing nodes with connections
- Data stream particles
- CRT scanline effect
- Cyberpunk aesthetic

This is active by default. No action needed.

## Option 2: Seedance Video (Requires API)

If you want the AI-generated video instead:

### Prerequisites
1. Get Replicate API token: https://replicate.com/account/api-tokens
2. Set environment variable:
   ```bash
   export REPLICATE_API_TOKEN=r8_your_token_here
   ```

### Generate Video
```bash
pip install replicate
python scripts/generate_landing_video.py
```

This will:
- Generate 20-second video with Seedance 2.0
- Save to `site/video/raven_intro.mp4`
- Cost: ~$0.50-1.00

### Extract Frames
```bash
python site/scripts/extract_frames.py site/video/raven_intro.mp4 site/frames 10
```

This extracts frames at 10 FPS (200 frames for 20s video).

### Deploy
```bash
git add -f site/frames/
git commit -m "chore: add landing video frames"
git push
```

Site will auto-deploy to https://ssrjkk.github.io/raven/

The site will automatically use video frames if they exist, otherwise falls back to procedural animation.

## Prompt Used

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

## Alternative Services

- **OpenRouter**: https://openrouter.ai/bytedance/seedance-2.5
- **BytePlus ModelArk**: https://docs.byteplus.com/en/docs/ModelArk/1520757

Both use similar prompts but may have different pricing and resolution options.
