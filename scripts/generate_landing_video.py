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

        url = str(output[0] if isinstance(output, list) else output)
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
    prompt = """Continuous first-person camera flight through abstract data architecture. Clean geometric aesthetic, modern glassmorphism. Dark background (#0a0812) with violet (#8b5cf6) and fuchsia (#d946ef) gradient glows.

Scene 1: Approach floating translucent glass panels with data streams flowing between them. Soft violet light bleeds through frosted surfaces.
Scene 2: Dive inside, thermal vision view — hot zones bright violet, cool zones deep indigo. Grain texture overlay.
Scene 3: Follow data packet through retrieval pipeline, clean typography scrolling past against dark void.
Scene 4: Enter neural chamber, geometric brain structure with pulsing transformer layers, gradient borders glowing.
Scene 5: Response text materializes in mid-air with subtle blur halos, modern terminal aesthetic.
Scene 6: Pull back to show unified system, fade to wireframe logo.

Glassmorphism, frosted glass panels, gradient borders, radial violet glows, subtle grain texture. Smooth continuous camera movement, no cuts."""

    output_path = Path("site/video/raven_intro.mp4")

    generate_video(prompt, output_path, duration=20)

    print()
    print("Next steps:")
    print("1. Keep the file out of git and add a <video> element to site/index.html that points at it")
    print("2. Push site/** to publish")


if __name__ == "__main__":
    main()
