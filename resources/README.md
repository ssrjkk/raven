# Raven AI mascot icon

Place your mascot `.ico` file here as `raven.ico`.

The icon is used by:
- Windows executable (`build/raven.spec`)
- Desktop app (`desktop/`)
- System tray icon

## Requirements

- Format: **.ico** (Windows icon)
- Recommended sizes: 256x256 (with embedded 32x32, 48x48, 64x64)
- Name: `raven.ico`

## Converting from PNG

Use any of these tools:
- **ImageMagick**: `magick convert mascot.png -define icon:auto-resize=256,64,48,32 resources/raven.ico`
- **icotool** (Linux): `icotool -c -o resources/raven.ico mascot.png`
- **online-convert.com**: https://www.Online-Convert.com

The existing spec will fall back to the default PyInstaller icon if this file is absent.
