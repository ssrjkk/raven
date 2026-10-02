"""Generate landing video using Seedance 2.0 via Replicate API."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

try:
    import replicate
except ImportError:
    print("Error: replicate package not installed")
    print("Install with: pip install replicate")
    sys.exit(1)


def generate_video(prompt: str, output_path: Path, duration: int = 20) -> None:
    """Generate video using Seedance 2.0."""
    api_token = os.environ.get("REPLICATE_API_TOKEN")
    if not api_token:
        print("Error: REPLICATE_API_TOKEN environment variable not set")
        print("Get your token at: https://replicate.com/account/api-tokens")
        print("Then set it: export REPLICATE_API_TOKEN=your_token_here")
        sys.exit(1)

    print("Generating video with Seedance 2.0...")
    print(f"Prompt: {prompt[:100]}...")
    print(f"Duration: {duration}s")
    print(f"Output: {output_path}")
    print()

    try:
        output = replicate.run(
            "bytedance/seedance-2.0",
            input={
                "prompt": prompt,
                "duration": duration,
                "resolution": "1080p",
            },
        )

        if not output:
            print("Error: No output from Replicate")
            sys.exit(1)

        print(f"Video generated: {output}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        url = str(output)
        if not url.startswith("https://"):
            msg = f"Refusing to download from non-HTTPS URL: {url[:80]}"
            raise RuntimeError(msg)

        print(f"Downloading to {output_path}...")
        with httpx.stream("GET", url, timeout=120.0, follow_redirects=True) as response:
            response.raise_for_status()
            with output_path.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)

        print(f"✓ Video saved to {output_path}")
        print(f"  Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")

    except Exception as e:
        print(f"Error generating video: {e}")
        sys.exit(1)


def main() -> None:
    prompt = """Continuous first-person camera flight through cyberpunk RAG architecture. Low-poly wireframe aesthetic, PS1 retro style. Dark background with violet (#8b5cf6) and fuchsia (#d946ef) glowing edges.

Scene 1: Approach massive wireframe server rack, data streams flowing between nodes.
Scene 2: Dive inside, thermal vision view — hot zones bright violet, cool zones deep indigo.
Scene 3: Follow data packet through retrieval pipeline, ASCII text scrolling past.
Scene 4: Enter neural chamber, low-poly brain structure with pulsing transformer layers.
Scene 5: Response text materializes in mid-air, CRT terminal aesthetic with scanlines.
Scene 6: Pull back to show unified system, fade to wireframe logo.

CRT monitor glow, scanline effect, cyberpunk atmosphere, technical visualization. Smooth continuous camera movement, no cuts."""

    output_path = Path("site/video/raven_intro.mp4")

    generate_video(prompt, output_path, duration=20)

    print()
    print("Next steps:")
    print(f"1. Extract frames: python site/scripts/extract_frames.py {output_path} site/frames 10")
    print("2. Commit frames: git add -f site/frames/ && git commit -m 'chore: add landing video frames'")
    print("3. Push: git push")
    print("4. Site will auto-deploy to https://ssrjkk.github.io/raven/")


if __name__ == "__main__":
    main()
