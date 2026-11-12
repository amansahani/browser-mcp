---
name: Browser MCP
description: Browse the live web with a real headless browser — search, read pages, fill forms, screenshots — via the `browser` MCP server. Load when a task needs current web content (search results, docs, prices, site status) or interaction with web pages, when a plain fetch-tool is insufficient or blocked.
---

# Browser MCP

A Playwright-powered MCP server exposing browser automation to agents. Requires the
`browser` MCP server to be registered in your agent (see the repo README for per-agent
installation — Claude Code, Claude Desktop, Cursor, VS Code, OpenCode).

Typical invocation (agents expose MCP tools namespaced by the server name):

```js
// opencode / code-mode style
await tools.browser.web_search({ query: "…", num_results: 5 })
```

```json
// JSON-RPC style (Claude Desktop etc.)
{ "method": "tools/call", "params": { "name": "web_search", "arguments": { "query": "…", "num_results": 5 } } }
```

## Tools

| Tool | Use |
| --- | --- |
| `web_search` | Web + academic papers. `source`: `auto` (default: Brave→Google→Marginalia, plus arXiv + OpenAlex), `brave`, `google`, `web`, `papers` |
| `navigate` | Open a URL; returns page content as Markdown (~15k char truncation) |
| `extract_text` | All visible text of the current page |
| `get_page_snapshot` | Accessibility tree — the token-efficient way to "look at" a page |
| `click` | Click a CSS selector |
| `fill` | Type into a form field by CSS selector |
| `evaluate_js` | Run JS in page context (escape hatch; returns a string) |
| `go_back` | History back |
| `get_current_url` | Current URL + title |
| `screenshot` | Full-viewport PNG as base64 |

## Working rules

- **One shared page.** All calls share a single Chromium page and persist across calls. `navigate` first; then `click`/`fill`/`extract_text` act on that page. Check `get_current_url` when unsure where you are.
- Call `navigate`, then read with `get_page_snapshot` (structure) or `extract_text` (prose).
- Prefer `get_page_snapshot` over raw HTML for deciding what to click/fill.
- Outputs are truncated at ~15k chars — for long pages, target content with `evaluate_js` (e.g. `document.querySelector('main').innerText`).
- `web_search`: papers come from the arXiv API (reliable, keyless) and OpenAlex; general web is Brave (API key optional — without one it falls back to the free headless SERP with a one-time "Verify" interstitial) then Google (can rate-limit under heavy use) then Marginalia. Search quality is much better for technical queries than consumer queries.
- Forms submitted via `click` may trigger full navigation — re-read the page state after.
- Screenshots return a base64 data URI; don't paste it into Markdown unless the user asked to see it.
- Rate-limit your usage: repeated Google hits trigger "unusual traffic" and the tool will serve Marginalia instead.

## When NOT to use it

- Static pages where a plain HTTP fetch tool works — cheaper and faster.
- Tasks requiring a logged-in personal browser session (fresh headless profile; your cookies do not exist here).
- Anything against a site whose ToS disallows automation — respect robots/ToS.
