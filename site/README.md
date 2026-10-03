# Raven landing site

Static site for <https://ssrjkk.github.io/raven/>. No build step, no bundler, no analytics,
no third-party request: GitHub Pages serves the files in this directory as they are.

## Files

```
site/
├── index.html                # the page: hero, registry, console, architecture, spec, setup
├── 404.html                  # served for unknown paths, styles only, no scripts
├── styles.css                # design tokens, self-hosted @font-face rules, every rule
├── fonts/                    # woff2 subsets used by styles.css
├── tools-data.js             # generated: the tool registry as raven-mcp reports it
├── mcp-frames.js             # generated: real request/response frames from raven-mcp
├── main.js                   # registry rendering, filters, reveal, copy buttons, bootstrap
├── terminal-demo.js          # replays the recorded frames, explains the ones missing
├── procedural-animation.js   # static hero canvas painted from the palette
├── favicon.svg
├── robots.txt
└── sitemap.xml
```

## Where the content comes from

`scripts/record_site_frames.py` starts `python -m raven.core.mcp --workspace .`,
exchanges eight frames with it and rewrites both generated files:

- `tools-data.js` — one entry per tool: name, category, description, parameter names with
  the types from its JSON Schema, and the required list. The registry section renders from
  this array, so the page can only show tools the server actually exposes.
- `mcp-frames.js` — the eight recorded `request`/`response` pairs, including the `-32602`
  reply to a `tools/call` with no tool name and the `-32601` reply to `resources/list`.
  The console replays these answers instead of inventing them.

Regenerate after any change to the tool registry or the protocol handler:

```bash
python scripts/record_site_frames.py
```

`tests/test_site_landing.py` fails if the committed generated files no longer match the
registry, if a hand-written count in `index.html` (tool count, version, channel adapters,
the hero's preview list) disagrees with the code, if a preset button has no recording
behind it, if `styles.css` names a `url()` or an `@font-face` source that does not ship,
if `index.html` or `404.html` loads an asset from a host other than GitHub, or if a file
appears in this directory that the page never loads.

## Fonts

Three families, latin subsets, all served from `fonts/` — the page makes no request to a
font host and needs no `preconnect` for one.

| family | used for | weights | file |
| --- | --- | --- | --- |
| IBM Plex Sans | prose, labels | 400, 500, 600 | `fonts/IBMPlexSans-latin.woff2` |
| Space Grotesk | wordmark, headings, figures | 700 | `fonts/SpaceGrotesk-latin.woff2` |
| IBM Plex Mono | code, tool names, JSON | 400, 500, 600 | `fonts/IBMPlexMono-latin-<weight>.woff2` |

124 KB in five files. Plex Sans and Space Grotesk are variable files, so one file per
family carries all the weights and each `@font-face` pins its own `font-weight`; IBM Plex
Mono ships a static instance per weight, so it is three files. Only the weights a rule in
`styles.css` actually asks for are declared — a declared face the browser never loads is
dead weight. Every face sets `font-display: swap`. All three families are licensed under
the SIL Open Font License 1.1.

One caveat of the latin subset: it stops before U+2190, so the `←`/`→` used in the console
line prefixes and in the connector label render from the system fallback rather than from
Plex. Anything else added to the page in that range needs the symbols subset.

To refresh a subset after changing a weight, request the CSS with a browser UA so Google
answers with woff2, then fetch each `url()` it returns:

```bash
curl -s -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36' \
  'https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400..600&display=swap' \
  | grep -o 'https://[^)]*woff2'
```

## Behaviour

- The registry cards are `<button>` elements: selecting one prefills a `tools/call` frame
  for that tool with its required arguments in the console input.
- The console accepts any frame you type. Frames matching the recording get the recorded
  answer; anything else gets a line saying a running server answers it, and the page does
  not pretend to be one.
- Both console bodies are scrollable regions exposed as `role="log"`, keyboard reachable,
  with no `aria-live` announcement per line.
- Section reveal is progressive enhancement: `main.js` adds a `js` class to `<html>` and
  only then does CSS hide a section before it is in view. With JavaScript off, every
  section is visible and the registry falls back to a `<noscript>` note.
- The hero canvas is painted once from the palette tokens (no random particles, no
  animation loop) and is `aria-hidden`.

## Local preview

```bash
python -m http.server 8000 --directory site
# open http://localhost:8000
```

## Deploy

`.github/workflows/deploy-site.yml` runs on every push to `main` that touches `site/**`:
it uploads this directory with `actions/upload-pages-artifact` and publishes it with
`actions/deploy-pages`. The site is served under the `/raven/` path, so asset references
here stay relative and `robots.txt` / `sitemap.xml` carry the absolute published URL.
