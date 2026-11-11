# Raven landing site

Static site for <https://ssrjkk.github.io/raven/>. No build step, no bundler, no analytics,
no third-party request: GitHub Pages serves the files in this directory as they are.

## Files

```
site/
├── index.html                # hero, counted numbers, features, request path, three ways in, page map
├── tools.html                # the registry and the request console
├── gateway.html              # adapter matrix, pairing policy, console screens
├── architecture.html         # request path, surfaces, counts
├── security.html             # six refusals, what never leaves
├── install.html              # three setup steps and the gateway commands
├── 404.html                  # served for unknown paths
├── styles.css                # design tokens, self-hosted @font-face rules, every rule
├── fonts/                    # woff2 subsets used by styles.css
├── tools-data.js             # generated: the tool registry as raven-mcp reports it
├── mcp-frames.js             # generated: real request/response frames from raven-mcp
├── stats.js                  # generated: every count the landing page states, measured from the tree
├── main.js                   # js flag, reveal, copy buttons, nav toggle, hero canvas
├── landing.js                # transport switch, counters, composition bars, pointer light, replay
├── registry.js               # registry rendering, filters and frame builder (tools page)
├── terminal-demo.js          # replays the recorded frames, explains the ones missing
├── procedural-animation.js   # static hero canvas painted from the palette
├── favicon.svg
├── og-image.png              # Open Graph social preview image (1200x630)
├── robots.txt
└── sitemap.xml
```

Each page carries its own canonical URL, Open Graph and Twitter metadata; `sitemap.xml`
lists the six content pages and the 404 page asks search engines not to index it.

## Where the content comes from

`scripts/record_site_frames.py` starts `python -m raven.core.mcp --workspace .`,
exchanges eight frames with it and rewrites the three generated files:

- `tools-data.js` — one entry per tool: name, category, description, parameter names with
  the types from its JSON Schema, and the required list. The registry on `tools.html`
  renders from this array, so the page can only show tools the server actually exposes.
- `mcp-frames.js` — the eight recorded `request`/`response` pairs, including the `-32602`
  reply to a `tools/call` with no tool name and the `-32601` reply to `resources/list`.
  The console replays these answers instead of inventing them.
- `stats.js` — the five numbers the landing page states (tools, channel adapters, console
  screens, optional groups, installed commands) and the tool count per category, counted
  from the same four sources the tests read: `tools/list`, `raven/channels/*/channel.py`,
  the `<Route path=…>` table in `web/src/App.tsx` and `pyproject.toml`. The page itself
  types no figure.

Regenerate after any change to the tool registry or the protocol handler:

```bash
python scripts/record_site_frames.py
```

`tests/test_site_landing.py` fails if the committed generated files no longer match the
registry, if a hand-written count on any page (tool count, version, channel adapters, the
hero's preview list) disagrees with the code, if a preset button has no recording behind
it, if `styles.css` names a `url()` or an `@font-face` source that does not ship, if any
page loads an asset from a host other than GitHub, if a page is missing from the nav or
the sitemap, or if a file appears in this directory that no page loads. It also fails on a
duplicated id or an `aria-labelledby`/`aria-controls`/`for` that names nothing, on a page
without its CSP and `color-scheme`, on a breadcrumb or social-image alt that disagrees with
the page, on a footer without the documentation link, on docs navigation without the way
back to the landing page, and on a registry that stopped reading its state from the hash.
It also fails if a group named on the install page is not published in
`pyproject.toml`, if the optional-group count the page states drifts from the packaging, or if
the page stops explaining what a missing group does to a control.
The markup is held to its own policy as well: no inline script, `on*` handler or `style`
attribute may ship while the meta tag forbids them, every page has one `h1` and no skipped
heading level, and `lang` plus the four landmarks are declared. Every code block has a
labelled copy button, the console field carries a name, and the registry cards take their
accessible name from the text on screen.

The generated numbers and the client that draws them are gated too. The suite fails if
`stats.js` is no longer what the tree measures, if a number in the markup stops matching
it, if the category bars are written into the page instead of computed, if the request
printed in the hero stops answering with the reply printed under it, if the transport
switch offers a route the server does not serve or rewrites a frame instead of a label, if
the refusal quoted in the request path is not the sentence `mcp_deny_reason` returns, if a
scroll-driven reveal survives `prefers-reduced-motion` instead of being switched off by
name, if a glass token is tinted with the accent rather than the ink, if any text colour
falls under 4.5:1 on a surface it can sit on, or if the landing page's first load grows
past 130 KB.

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

- Every page shares the same seven-link nav; the current page carries `aria-current="page"`.
  Below 900px the links move into a panel the menu button opens, and Escape closes it.
- The registry cards are `<button>` elements: selecting one pre-fills a `tools/call` frame
  for that tool with its required arguments and moves focus to the console input. The
  address bar carries the state: `#tool=read` fills the console and highlights that card
  without moving focus, `#cat=file` opens a filter, both update through `replaceState`, and
  a name the server did not report is ignored rather than rendered. A card is named by its
  visible tool name and described by its description, not by a hidden sentence. When a
  search or filter matches nothing, the reset button clears both, drops the hash and puts
  focus back in the search box; `/` focuses that box from anywhere outside a field.
- Every page declares a Content-Security-Policy that allows only same-origin scripts,
  styles, fonts and images and forbids `connect-src` outright, plus a dark `color-scheme`
  in the meta tag and `:root`, so native controls and scrollbars stay dark. The footer
  links the published documentation at `/raven/docs/`, and its nav ends with a link back
  to the landing page.
- Each code block has a copy button that reports through a `role="status"` live region.
  Where the Clipboard API does not exist — a preview served over plain http from a LAN
  address — the click selects the code instead and says to press Ctrl+C, rather than
  asking the visitor to select text it never selected.
- The console accepts any frame you type. Frames matching the recording get the recorded
  answer; anything else gets a line saying a running server answers it, and the page does
  not pretend to be one. The input is labelled `JSON-RPC frame`, grows to fit a multi-line
  frame instead of scrolling it inside the box, and is cleared once a frame is sent; Up/Down
  recall the frames already sent, shell-style, restoring the draft on the way back. Inside
  a multi-line frame the arrows move the caret and only recall from the first line up or the
  last line down, and a keystroke belonging to an IME composition is left to the IME — the
  same rule keeps `/` from stealing a character typed through one.
- Both console bodies are scrollable regions exposed as `role="log"` with `aria-live="polite"`,
  keyboard reachable, so screen readers announce new lines as they appear.
- Section reveal is progressive enhancement: `main.js` adds a `js` class to `<html>` and
  only then does CSS hide a section before it is in view. With JavaScript off, every
  section is visible and the registry falls back to a `<noscript>` note.
- The hero console says which transport carried the frames, and a two-option switch rewrites
  the two route labels under the title: stdio names the pipe `python -m raven.core.mcp`
  reads, HTTP names `POST /mcp/rpc` and the bearer header that authorises it. Only the labels
  change — the frames stay what the recorder exchanged, on either transport. With scripting
  off the switch is not offered at all.
- The five numbers count up when the section scrolls into view and land exactly on the value
  in `stats.js`. Without JavaScript, or with motion reduced, the number already in the markup
  is the number you read — nothing is hidden behind the animation.
- The category split under those numbers is built from the same file: one row per category,
  each bar sized against the largest category and the exact count carried as text, so no
  width is chosen by hand. The list labels itself with the total it was computed from.
- The request-path stages draw their connector as they cross the viewport where the browser
  supports `animation-timeline: view()`, and are simply drawn where it does not. Under
  `prefers-reduced-motion: reduce` the animation is dropped by name, not just slowed, so a
  scroll-linked stage cannot stay invisible at `opacity: 0`.
- Cards, doors and explore tiles carry a pointer light that moves with the pointer and stops
  under reduced motion. Pages of the site cross-fade on one document transition where the
  browser supports `@view-transition`, and the same rule turns that off for reduced motion.
- The hero canvas is painted once from the palette tokens (no random particles, no
  animation loop) and is `aria-hidden`. Under `prefers-reduced-motion: reduce` it centres
  the light and ignores the pointer, so the surface stays still.

## Local preview

```bash
python -m http.server 8000 --directory site
# open http://localhost:8000
```

## Deploy

`.github/workflows/deploy-site.yml` is the only workflow that publishes Pages. It runs on
every push to `main` that touches `site/**`, `docs/**` or `mkdocs.yml`: it builds the
MkDocs documentation into `build/docs` (`site_dir` in `mkdocs.yml`, never this directory),
stages this directory as `build/pages` with the documentation copied to
`build/pages/docs/`, and uploads that tree with `actions/upload-pages-artifact` and
`actions/deploy-pages`. The landing page is served at the site root and the documentation
under `/raven/docs/`, so asset references here stay relative and `robots.txt` /
`sitemap.xml` carry the absolute published URL.

The documentation builds with `strict: true` in `mkdocs.yml`: a broken internal link or a
page outside the nav fails the workflow instead of shipping. `docs/archive/` is excluded
from the build, so session notes stay in the repository and off the published site.

The theme is installed pinned, and an audit step after the build fails the run if any built
documentation page fetches a stylesheet, script or font from a host other than the published
site — Material loads Roboto from Google Fonts unless `mkdocs.yml` turns that off, and a
self-hosted server should not hand a visitor's IP address to someone else. The same audit
fails when `build/docs` is missing, so a build that silently produced nothing cannot pass.
