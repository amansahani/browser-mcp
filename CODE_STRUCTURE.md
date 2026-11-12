# Code Structure — Browser MCP

Architecture and code layout of the Browser MCP server.

## Project Layout

```
browser_mcp/
├── server.py           # MCP server — all tools and search backends live here
├── test_server.py      # Smoke test — lists registered tools
├── pyproject.toml      # Metadata, dependencies, console script entry point
└── README.md           # Usage & client configuration
```

Single-file design by intention: deployment is one command (`python server.py`) and the whole system is readable in one sitting.

## `server.py` — Section-by-Section Breakdown

~630 lines, organized into these blocks:

```
Header docstring        module overview + tool list
Imports                 FastMCP, Playwright async API, markdownify, bs4
Lifespan manager        one shared Chromium across all tool calls
FastMCP instance        "BrowserMCP", instructions for connected clients
HTTP/search backends    plain-HTTP helpers + Brave/Google/Marginalia/arXiv/OpenAlex
Tool definitions        10 MCP tools
Entry point             `mcp.run()` — stdio by default, SSE optionally
```

### Browser lifespan

`browser_lifespan` launches **one headless Chromium** at server startup and
shares it across every tool call (shared cookies/session, no ~2s cold start
per request). Anti-detection: `--disable-blink-features=AutomationControlled`
+ a desktop Chrome user-agent.

The one shared `Page` is what `ctx` carries; `_get_page(ctx)` returns it.
All interaction tools (navigate/click/fill/screenshot/…) operate on it.

### Search backends (`web_search`)

Bing and DuckDuckGo hard-block datacenter/residential egress with ads or
HTTP 202 + CAPTCHA, so search does **not** scrape them. Instead:

| Backend | Transport | Key required | Notes |
|---|---|---|---|
| **Brave Search API** | plain HTTP | yes (`~/.browser-mcp/brave_api_key` to opt in) | Best quality; automatic fallback if unavailable |
| **Brave (headless SERP)** | the bundled Chromium | no | Free; one-time "Verify" JS challenge per session |
| **Google (headless SERP)** | the bundled Chromium | no | Intermittent bot flag; auto-falls-back |
| **Marginalia** | plain HTTP | no | Independent index; follows its 1s signed "wait" page |
| **OpenAlex** | plain HTTP (JSON) | no | Academic papers, polite-pool |
| **arXiv API** | plain HTTP (Atom XML) | no | Academic papers, reliable |

Chain in `source="auto"`: Brave (API or headless) → Google → Marginalia, plus
papers (OpenAlex + arXiv). `source` can be `brave|google|web|papers`.

### Tools (10)

| Tool | Purpose |
|---|---|
| `web_search` | Web + papers; returns Markdown results |
| `navigate` | Open URL → page content as Markdown (~15k cap) |
| `click` / `fill` | Interact with the page by CSS selector |
| `screenshot` | Viewport PNG as base64 |
| `extract_text` | `document.body.innerText` |
| `get_page_snapshot` | Accessibility tree (token-efficient structure) |
| `evaluate_js` | Arbitrary JS in page context |
| `go_back` | History back |
| `get_current_url` | Current URL + title |

## Data Flow

```
AI agent ── MCP JSON-RPC (stdio/SSE) ──► FastMCP ── @mcp.tool() handler ──► Playwright ──► Chromium ──► HTTP
```

One browser per server process; one shared page per lifetime; results returned
as strings.

## Design Decisions

| Decision | Rationale |
|---|---|
| Shared single browser | No per-call cold start; matches how agents actually browse |
| No Google/Bing/DDG scraping | Bot-flagged egress; use keyless independents instead |
| Markdown output | Token-efficient for agents |
| 15k char truncation | Context window protection |
| Accessibility-tree snapshot tool | Structured view beats raw HTML for agents |
| Single-file design | Trivial deploy: `python server.py` |
