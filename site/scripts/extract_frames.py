"""Extract frames from video for scroll-driven animation."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def extract_frames(video_path: Path, output_dir: Path, fps: int = 10) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-vf", f"fps={fps},scale=1920:-1:flags=lanczos",
        "-q:v", "2",
        "-start_number", "0",
        str(output_dir / "frame_%04d.jpg"),
    ]

    print(f"Extracting frames at {fps} FPS...")
    print(f"Input: {video_path}")
    print(f"Output: {output_dir}/frame_XXXX.jpg")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    frames = list(output_dir.glob("frame_*.jpg"))
    print(f"Extracted {len(frames)} frames")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python extract_frames.py <video_path> [output_dir] [fps]")
        print("Example: python extract_frames.py raven_intro.mp4 frames 10")
        sys.exit(1)

    video_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("frames")
    fps = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    if not video_path.exists():
        print(f"Error: Video file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    extract_frames(video_path, output_dir, fps)


if __name__ == "__main__":
    main()
