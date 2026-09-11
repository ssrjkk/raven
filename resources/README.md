# Raven AI mascot icon

Place your mascot `.ico` file here as `raven.ico`.

The icon is used by:
- Windows executable (`scripts/raven.spec` → `packaging/dist/Raven.exe`)

If `resources/raven.ico` is absent, the build pipeline generates it automatically
via `scripts/make_icon.py` (a violet→indigo gradient bird), so you only need to
drop a custom file here if you want a different mascot.

## Requirements

- Format: **.ico** (Windows icon)
- Recommended sizes: 256x256 (with embedded 32x32, 48x48, 64x64)
- Name: `raven.ico`

## Converting from PNG

Use any of these tools:
- **ImageMagick**: `magick convert mascot.png -define icon:auto-resize=256,64,48,32 resources/raven.ico`
- **icotool** (Linux): `icotool -c -o resources/raven.ico mascot.png`
- **online-convert.com**: https://www.Online-Convert.com

The spec falls back to the auto-generated icon if this file is absent.
