# Browser MCP Server

A **Playwright-powered MCP (Model Context Protocol) server** that gives AI agents a real headless browser — web search, page reading, clicks, form filling and screenshots — over MCP (`stdio` by default).

Ships with an **agent-ready skill** (`skills/browser-mcp/SKILL.md`) so agents know when and how to use it.

## Install (one command)

```bash
./scripts/setup.sh
```

This creates `.venv`, installs the package + Chromium, installs the skill into any detected agent skills directory (OpenCode, Claude Code), and prints ready-to-paste MCP config snippets for your agent.

Prefer to do it by hand?

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium   # one-time; cache at ~/.cache/ms-playwright
```

## Add it to your agent

After install, the `browser-mcp` binary is at `<project>/.venv/bin/browser-mcp`.
Or skip a venv entirely: `pipx install .` puts `browser-mcp` on your `PATH`.

| Agent | Command / config |
|---|---|
| **OpenCode** | Add to `~/.config/opencode/opencode.json`:<br>```jsonc<br>{ "mcp": { "servers": { "browser": {<br>  "type": "local",<br>  "command": ["/absolute/path/.venv/bin/browser-mcp"],<br>  "disabled": false<br>} } } }<br>```<br>then check `opencode mcp list` → `✓ browser connected` |
| **Claude Code** | `claude mcp add browser -- /absolute/path/.venv/bin/browser-mcp`<br>or add to `~/.claude.json` → `mcpServers` |
| **Claude Desktop** | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):<br>```json<br>{ "mcpServers": { "browser": { "command": "/absolute/path/.venv/bin/browser-mcp" } } }<br>``` |
| **Cursor / VS Code** | `.cursor/mcp.json` or `.vscode/mcp.json`:<br>```json<br>{ "servers": { "browser": { "command": "/absolute/path/.venv/bin/browser-mcp" } } }<br>``` |
| **Any MCP client** | Point it at the `browser-mcp` binary, transport `stdio` |

Private GitHub repo? `pip install git+https://github.com/amansahani/browser-mcp.git` works once you've authenticated git (e.g. `gh auth setup-git`) — or just clone and `./scripts/setup.sh`.

## Add the skill

The skill tells agents *when* to load the browser tools and how to use them well.

```bash
# automatic (if the agent dir exists) — what scripts/setup.sh does:
mkdir -p ~/.config/opencode/skills/browser-mcp && cp skills/browser-mcp/SKILL.md ~/.config/opencode/skills/browser-mcp/
mkdir -p ~/.claude/skills/browser-mcp         && cp skills/browser-mcp/SKILL.md ~/.claude/skills/browser-mcp/
```

Or copy `skills/browser-mcp/` into whatever skills directory your agent uses — it's a plain Markdown file with frontmatter (`name`, `description`).

## Tools

| Tool | Description |
|---|---|
| `web_search` | Search: Brave (API if key set in `~/.browser-mcp/brave_api_key`, else free headless SERP) → Google headless → Marginalia, plus arXiv + OpenAlex papers. `source`: `auto`, `brave`, `google`, `web`, `papers` |
| `navigate` | Open a URL, page content as Markdown (~15k chars) |
| `click` | Click a CSS selector |
| `fill` | Type into a form field by CSS selector |
| `screenshot` | Viewport PNG as base64 |
| `extract_text` | All visible text on the current page |
| `get_page_snapshot` | Accessibility tree (token-efficient structured view) |
| `evaluate_js` | Arbitrary JavaScript in page context |
| `go_back` | History back |
| `get_current_url` | Current URL + title |

> **Why no Google/Bing/DDG scrape?** Many networks' egress is bot-flagged — Bing serves spam/ads and DuckDuckGo returns HTTP 202 + CAPTCHA there (IP-reputation based, independent of UA). `web_search` chains **Brave Search** first — via the official API when `~/.browser-mcp/brave_api_key` (or `$BRAVE_API_KEY`, mode 600) exists, otherwise via the free headless SERP (one "Verify" click per browser session, done by the page's own JS) — then **Google headless** (intermittent; trips "unusual traffic" if hit repeatedly), then **Marginalia** (independent index), plus **arXiv's API** and **OpenAlex** for academic papers (no keys). Don't run search in a tight loop.

## Architecture

- **Transport:** stdio (default) or `--transport sse` / `--transport streamable-http` (see `--help`)
- **Browser:** headless Chromium via Playwright; one shared browser + page across all tool calls
- **Content format:** HTML → Markdown for agents; pages truncate at ~15k chars

## Development

```bash
pip install -e .
python test_server.py     # smoke test — lists registered tools
python server.py --help   # CLI: --transport stdio|sse|streamable-http [--host H] [--port N]
```

## License

MIT — see [LICENSE](LICENSE).
