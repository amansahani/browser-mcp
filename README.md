# Browser MCP Server

A **Playwright-powered MCP (Model Context Protocol) server** that exposes browser automation tools for AI agents to browse and search the internet.

## Features

| Tool | Description |
|---|---|
| `web_search` | Search: Brave (API if key set, else free headless SERP) → Google headless → Marginalia, plus arXiv + OpenAlex papers — `source`: `auto`, `brave`, `google`, `web`, `papers` |
| `navigate` | Open a URL and get the page content as Markdown |
| `click` | Click an element by CSS selector |
| `fill` | Fill a form field by CSS selector |
| `screenshot` | Capture the current page as a base64 PNG |
| `extract_text` | Extract all visible text from the page |
| `get_page_snapshot` | Get the accessibility tree (structured page view) |
| `evaluate_js` | Run JavaScript in the page context |
| `go_back` | Navigate back in history |
| `get_current_url` | Get the current URL and title |

> **Why no Google/Bing/DDG scrape?** Many networks' egress is bot-flagged — Bing serves spam/ads and DuckDuckGo returns HTTP 202 + CAPTCHA to any client there (IP-reputation based, independent of UA). `web_search` therefore chains **Brave Search** first — via the official API when `~/.browser-mcp/brave_api_key` (or `$BRAVE_API_KEY`, mode 600) exists, **otherwise via the free headless SERP in the bundled Chromium** (one "Verify" click per browser session, performed by the page's own JS) — then **Google headless** (intermittent; trips "unusual traffic" if hit repeatedly), then **Marginalia** (independent index, text-browser HTML), plus **arXiv's official API** and **OpenAlex** for academic papers (no keys). `source`: `auto` (Brave→Google→Marginalia + arXiv + OpenAlex), `brave`, `google`, `web`, `papers`. Rate-limit your calls — don't run search in a loop.

## Quick Start

```bash
# Dedicated virtual environment (mcp 1.x API; the server pins mcp<2)
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium   # only if needed; cache at ~/.cache/ms-playwright

# Run the server (stdio transport — for MCP clients)
python server.py

# Or run with SSE transport for HTTP access
python server.py --transport sse --port 8000
```

## Client Configuration

### OpenCode

Register the server globally so OpenCode launches it automatically over stdio —
no manual start. Add this to your OpenCode config:

```jsonc
{
  "mcp": {
    "servers": {
      "browser": {
        "type": "local",
        "command": ["/absolute/path/to/browser_mcp/.venv/bin/python", "/absolute/path/to/browser_mcp/server.py"],
        "cwd": "/absolute/path/to/browser_mcp",
        "disabled": false
      }
    }
  }
}
```

Verify with `opencode mcp list` → `✓ browser connected`.

### Generic JSON MCP client

```json
{
  "mcpServers": {
    "browser": {
      "command": "/absolute/path/to/browser_mcp/.venv/bin/python",
      "args": ["/absolute/path/to/browser_mcp/server.py"]
    }
  }
}
```

### FastMCP CLI

```bash
fastmcp run server.py
```

## Architecture

- **Transport:** stdio (default) or SSE
- **Browser:** Headless Chromium via Playwright
- **Lifespan:** A single browser instance is shared across all tool calls for efficiency
- **Content format:** HTML is converted to Markdown for LLM-friendly output; pages are truncated to ~15k chars

## License

MIT
