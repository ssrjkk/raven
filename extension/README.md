# Raven extensions

_by [@ssrjkk](https://github.com/ssrjkk)_

Two independent client integrations live here:

| Path | Target | Manifest | Notes |
|------|--------|----------|-------|
| `manifest.json`, `src/`, `icons/` | Chrome / Edge (MV3) | `manifest.json` | Side-panel chat client talking to the local gateway (`http://localhost:18888`, WS `/ws`) |
| `vscode/` | VS Code (>= 1.93) | `vscode/package.json` | TypeScript extension source in `vscode/src/`, compiled output in `vscode/out/` |

## Browser extension

- `src/background.js` — service worker (opens the side panel, proxies `type: "query"` messages to `/api/status`)
- `src/popup/index.html`, `src/popup/popup.css`, `src/popup/popup.js` — the chat client: own CSS and vanilla JS, no
  framework and nothing loaded from another host, because MV3 prohibits remotely hosted code and the manifest pins
  `script-src 'self'`
- `icons/icon16.png`, `icons/icon48.png`, `icons/icon128.png` — required by `manifest.json`

The gateway's `/ws` authenticates, so the panel needs a token: open **settings** in the popup and enter the gateway
URL plus `WEB_SECRET_KEY` (or a session token). It is kept in `chrome.storage.local` and sent as `?token=`, the same
way the web UI sends it.

Load it with `chrome://extensions` → *Load unpacked* → select this directory.

## VS Code extension

```bash
cd extension/vscode
npm install
npm run compile     # tsc -p ./  -> out/
npm run package     # vsce package (requires the icon below)
```

## Icons

All PNG icons (browser + VS Code) and the PyInstaller `scripts/raven.ico` come from the
same renderer (`scripts/icon_render.py`) so the branding stays identical everywhere:

```bash
python scripts/make_icon.py                 # scripts/raven.ico (skip if present)
python scripts/make_extension_icons.py      # write missing extension icons
python scripts/make_extension_icons.py --force   # regenerate every extension icon
```

The generated PNGs are committed — `manifest.json` and `vscode/package.json` reference them at
build/package time.
