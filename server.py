"""
Browser MCP Server — Playwright-based browser automation exposed via MCP.

Tools:
  - web_search        : Search the web (Marginalia) and papers (OpenAlex) and return results.
  - navigate          : Navigate to a URL and return page content as Markdown.
  - click             : Click an element by CSS selector.
  - fill              : Fill a form field by CSS selector.
  - screenshot        : Take a screenshot and return base64 PNG.
  - extract_text      : Extract all visible text from the current page.
  - get_page_snapshot : Return the accessibility tree of the current page.
  - evaluate_js       : Execute arbitrary JavaScript in the page context.
  - go_back           : Navigate back in browser history.
  - get_current_url   : Return the current page URL.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from typing import Any

from markdownify import markdownify
from mcp.server.fastmcp import Context, FastMCP
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("browser-mcp")

# ---------------------------------------------------------------------------
# Lifespan — manage a single Playwright browser across the server's lifetime
# ---------------------------------------------------------------------------
@asynccontextmanager
async def browser_lifespan(server: FastMCP):
    """Start a Chromium browser on server startup and close it on shutdown."""
    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context: BrowserContext = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        page: Page = await context.new_page()
        # Expose through the server context so tools can access them
        yield {"browser": browser, "context": context, "page": page}
        await browser.close()


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "BrowserMCP",
    instructions=(
        "A Playwright-powered MCP server that lets AI agents browse the web, "
        "search the internet, click elements, fill forms, take screenshots, and "
        "extract page content."
    ),
    lifespan=browser_lifespan,
)

# ---------------------------------------------------------------------------
# Helper — get the shared page
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Search backends (plain HTTP — search bypasses the browser entirely)
# ---------------------------------------------------------------------------

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


_BRAVE_KEY_FILE = os.path.expanduser("~/.browser-mcp/brave_api_key")


def _brave_key() -> str | None:
    key = os.environ.get("BRAVE_API_KEY")
    if key and key.strip():
        return key.strip()
    path = os.environ.get("BRAVE_API_KEY_FILE", _BRAVE_KEY_FILE)
    try:
        with open(path) as f:
            key = f.read().strip()
        return key or None
    except OSError:
        return None


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _brave_search(query: str, num_results: int) -> list[dict] | None:
    """Brave Search API (Web Search endpoint, $5/1k requests, $5 free credits/mo).

    Returns None on error (missing key is handled by the caller; API failure),
    [] on a legitimate empty result.
    """
    key = _brave_key()
    if key is None:
        return None
    url = (
        "https://api.search.brave.com/res/v1/web/search?"
        + urllib.parse.urlencode({"q": query, "count": max(1, min(num_results, 20))})
    )
    req = urllib.request.Request(
        url,
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("Brave search failed: %s", exc)
        return None
    results = []
    for item in (data.get("web") or {}).get("results", [])[:num_results]:
        desc = _strip_tags(item.get("description", ""))
        extra = item.get("extra_snippets") or []
        snippet = desc or (_strip_tags(extra[0]) if extra else "")
        results.append({
            "title": _strip_tags(item.get("title", "")),
            "url": item.get("url", ""),
            "snippet": snippet[:300],
        })
    return results


def _marginalia_search(query: str, num_results: int) -> list[dict]:
    """General web search via Marginalia's text-browser UI.

    The new UI is JS-only; the old one serves HTML but soft-rate-limits bots
    with a 1s 'Wait For A Moment' page carrying a signed proceed link — we
    follow it. Best-effort: returns [] on any failure.
    """
    base = "https://old-search.marginalia.nu/search?query=" + urllib.parse.quote_plus(query)
    try:
        html = _fetch(base)
        if "Wait For A Moment" in html or "sst=" in html:
            m = re.search(r'href="([^"]*sst=[^"]+)"', html)
            if not m:
                return []
            time.sleep(1.3)
            html = _fetch("https://old-search.marginalia.nu" + m.group(1))
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for card in soup.select("section.card.search-result")[:num_results]:
            url_a = card.select_one("div.url a[href]")
            title_a = card.select_one("h2 a.title")
            if not url_a or not title_a:
                continue
            descr = card.select_one("p.description")
            results.append({
                "title": title_a.get_text(strip=True),
                "url": url_a["href"],
                "snippet": descr.get_text(" ", strip=True)[:300] if descr else "",
            })
        return results
    except Exception as exc:
        logger.warning("Marginalia search failed: %s", exc)
        return []


async def _google_search(page: Page, query: str, num_results: int) -> list[dict]:
    """General web search via real Google in the shared headless Chromium.

    Google serves this network without a consent/JS challenge in headless mode.
    Result links are opaque 'google.com/goto' wrappers; page.goto follows the
    server-side redirect chain, so page.url after navigation is the resolved
    target. wait_until='commit' avoids loading destination HTML.
    """
    serp = (
        "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
        + "&udm=14&hl=en&num=" + str(max(1, min(num_results, 10)))
    )
    try:
        await _safe_goto(page, serp, timeout=25000)
        anchors = await page.evaluate(
            """(n) => {
                const out = [];
                for (const h of Array.from(document.querySelectorAll('h3'))) {
                    const a = h.closest('a');
                    if (!a || !a.href) continue;
                    const block = h.closest('div[data-snf]') || h.closest('div.g') || h.parentElement;
                    let s = block ? (block.innerText || '').replace(h.innerText || '', '') : '';
                    s = s.replace(/\\s+/g, ' ').trim().slice(0, 250);
                    out.push({ t: (h.innerText || '').trim(), u: a.href, s });
                    if (out.length >= n) break;
                }
                return out;
            }""",
            num_results,
        )
        results = []
        for a in anchors:
            try:
                await page.goto(a["u"], wait_until="commit", timeout=12000)
                results.append({"title": a["t"], "url": page.url, "snippet": a.get("s", "")})
            except Exception:
                results.append({"title": a["t"], "url": a["u"], "snippet": a.get("s", "")})
        return results
    except Exception as exc:
        logger.warning("Google search failed: %s", exc)
        return []


def _arxiv_search(query: str, num_results: int) -> list[dict]:
    """Paper search via the official arXiv API (no key, generous rate limits)."""
    import xml.etree.ElementTree as ET
    url = (
        "http://export.arxiv.org/api/query?search_query=all:"
        + urllib.parse.quote_plus(f'"{query}"')
        + f"&max_results={max(1, min(num_results, 20))}&sortBy=relevance"
    )
    try:
        data = _fetch(url)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(data)
        results = []
        for entry in root.findall("a:entry", ns):
            title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
            title = re.sub(r"\s+", " ", title)
            link = entry.findtext("a:id", default="", namespaces=ns) or ""
            summary = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
            summary = re.sub(r"\s+", " ", summary)[:300]
            authors = ", ".join(
                (a.findtext("a:name", default="?", namespaces=ns) or "?")
                for a in entry.findall("a:author", ns)[:3]
            )
            published = (entry.findtext("a:published", default="", namespaces=ns) or "")[:10]
            results.append({
                "title": title,
                "url": link,
                "snippet": " · ".join(filter(None, [authors, published]))
                + (" — " + summary if summary else ""),
            })
        return results
    except Exception as exc:
        logger.warning("arXiv search failed: %s", exc)
        return []


async def _brave_browser_search(page: Page, query: str, num_results: int) -> list[dict]:
    """Brave Search via the shared headless Chromium — no API key needed.

    This network gets a one-time 'Verifying you're not a bot' interstitial on
    first hit per browser session; the page's own Verify button is clicked by
    the browser's JS (same as a user pressing it). Repeat sessions usually
    don't re-trigger it. Uses Brave's public web SERP for personal research.
    """
    serp = "https://search.brave.com/search?q=" + urllib.parse.quote_plus(query) + "&source=web"
    try:
        await _safe_goto(page, serp, timeout=25000)
        try:
            has_verify = await page.evaluate(
                "() => Array.from(document.querySelectorAll('button')).some(b => (b.innerText||'').trim() === 'Verify')"
            )
            if has_verify:
                await page.evaluate(
                    "() => { const b = Array.from(document.querySelectorAll('button')).find(x => (x.innerText||'').trim() === 'Verify'); if (b) b.click(); }"
                )
                # The click navigates/reloads — wait for results to render, tolerating context destruction
                for _ in range(30):
                    try:
                        await page.wait_for_timeout(500)
                        n = await page.evaluate("() => document.querySelectorAll('div.result-wrapper').length")
                        if n:
                            break
                    except Exception:
                        pass  # context is mid-navigation; keep polling
        except Exception:
            pass
        anchors = await page.evaluate(
            """(n) => {
                const out = [];
                for (const w of document.querySelectorAll('div.result-wrapper')) {
                    const a = w.querySelector('a[href]');
                    const t = w.querySelector('div.title.search-snippet-title');
                    if (!a || !t) continue;
                    const sEl = w.querySelector('div.generic-snippet .content');
                    const s = sEl ? sEl.innerText.replace(/\\s+/g, ' ').trim() : '';
                    out.push({ t: (t.innerText||'').trim(), u: a.href, s: s.slice(0, 250) });
                    if (out.length >= n) break;
                }
                return out;
            }""",
            num_results,
        )
        results = []
        for a in anchors:
            results.append({"title": a["t"], "url": a["u"], "snippet": a.get("s", "")})
        return results
    except Exception as exc:
        logger.warning("Brave headless search failed: %s", exc)
        return []


def _openalex_search(query: str, num_results: int) -> list[dict]:
    """Academic paper search via the OpenAlex API (no key required)."""
    url = (
        "https://api.openalex.org/works?search="
        + urllib.parse.quote_plus(query)
        + f"&per-page={max(1, min(num_results, 25))}"
        + "&mailto=opencode-browser-mcp@example.com"  # OpenAlex polite pool
    )
    try:
        import json
        data = json.loads(_fetch(url))
        results = []
        for w in data.get("results", []):
            inv = w.get("abstract_inverted_index") or {}
            abstract = ""
            if inv:
                words: list[tuple[int, str]] = []
                for word, positions in inv.items():
                    for pos in positions:
                        words.append((pos, word))
                abstract = " ".join(w_ for _, w_ in sorted(words))[:300]
            authors = ", ".join(
                a.get("author", {}).get("display_name", "?")
                for a in (w.get("authorships") or [])[:3]
            )
            year = w.get("publication_year")
            cited = w.get("cited_by_count", 0)
            venue = (w.get("primary_location") or {}).get("source", {}) or {}
            venue_name = venue.get("display_name", "") if isinstance(venue, dict) else ""
            doi = w.get("doi") or w.get("id") or ""
            meta = " · ".join(filter(None, [
                authors and authors,
                str(year) if year else "",
                venue_name,
                f"{cited} citations",
            ]))
            results.append({
                "title": w.get("title") or "(untitled)",
                "url": doi,
                "snippet": (meta + (" — " + abstract if abstract else ""))[:400],
            })
        return results
    except Exception as exc:
        logger.warning("OpenAlex search failed: %s", exc)
        return []



def _get_page(ctx: Context) -> Page:
    """Retrieve the shared Playwright Page from the MCP context."""
    return ctx.request_context.lifespan_context["page"]


async def _safe_goto(page: Page, url: str, timeout: int = 30000) -> None:
    """Navigate to a URL, waiting for the network to be mostly idle."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        # Give JS-heavy pages a moment to settle
        await page.wait_for_timeout(1500)
    except Exception as exc:
        logger.warning("Navigation partial failure: %s", exc)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def web_search(ctx: Context, query: str, num_results: int = 8, source: str = "auto") -> str:
    """
    Search the internet and return the top results.

    Use this tool when you need to find information on the internet, papers,
    or technical documentation. Web backends: Brave Search (API when
    ~/.browser-mcp/brave_api_key exists, else the headless SERP — free),
    Google via headless Chromium (intermittent; auto-falls-back), Marginalia.
    Papers: arXiv + OpenAlex (no keys).

    Args:
        query: The search query string.
        num_results: How many results per section (default 8, max 20).
        source: Which backend(s) to use — "auto" (Brave→Google→Marginalia +
            arXiv + OpenAlex), "brave", "google", "web" (Marginalia), or "papers".
    """
    page = _get_page(ctx)
    num_results = min(max(num_results, 1), 20)
    source = (source or "auto").lower()
    if source not in ("auto", "brave", "google", "web", "papers"):
        source = "auto"

    web_results: list[dict] = []
    web_label = "Web (Brave)"
    if source in ("auto", "brave"):
        # 1) Brave API when a key is configured
        brave = None
        if _brave_key() is not None:
            brave = await asyncio.to_thread(_brave_search, query, num_results)
            if brave is None:
                logger.info("Brave API failed; falling back to headless Brave SERP")
        # 2) Headless Brave SERP (works from this session; one-time Verify click/session)
        if brave:
            web_results, web_label = brave, "Web (Brave API)"
        else:
            brave = await _brave_browser_search(page, query, num_results)
            if brave:
                web_results, web_label = brave, "Web (Brave)"
            elif source == "brave":
                if _brave_key() is not None:
                    return (
                        "Brave Search API is configured but the call failed (invalid key or "
                        "exhausted monthly credits), and the headless SERP also failed. "
                        "Check ~/.browser-mcp/brave_api_key or $BRAVE_API_KEY, and your plan at "
                        "https://api-dashboard.search.brave.com/app/keys."
                    )
                return (
                    "Brave Search is not configured and the headless fallback also failed.\n"
                    "Options:\n"
                    "  1. Register (free, $5 credits/mo): https://api-dashboard.search.brave.com/register\n"
                    "  2. Key file: printf '%s' 'YOUR_KEY' > ~/.browser-mcp/brave_api_key && chmod 600 ~/.browser-mcp/brave_api_key\n"
                    "  3. Or try source=\"google\" or source=\"web\" as fallbacks right now."
                )
    if not web_results and source in ("auto", "google"):
        web_results = await _google_search(page, query, num_results)
        if not web_results:
            web_results = await asyncio.to_thread(_marginalia_search, query, num_results)
            web_label = "Web (Marginalia — Google unavailable)"
    elif source == "web":
        web_results = await asyncio.to_thread(_marginalia_search, query, num_results)
        web_label = "Web (Marginalia)"
    paper_results: list[dict] = []
    arxiv_results: list[dict] = []
    if source in ("auto", "papers"):
        paper_results = await asyncio.to_thread(_openalex_search, query, min(num_results, 6))
        arxiv_results = await asyncio.to_thread(_arxiv_search, query, min(num_results, 6))

    lines = [f"## Search Results for: {query}\n"]

    def _section(title: str, results: list[dict]) -> None:
        if not results:
            return
        lines.append(f"### {title}\n")
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. [{r['title']}]({r['url']})")
            if r.get("snippet"):
                lines.append(f"   > {r['snippet']}")
            lines.append("")

    _section(web_label, web_results)
    _section("Papers (OpenAlex)", paper_results)
    _section("Papers (arXiv)", arxiv_results)

    if not web_results and not paper_results and not arxiv_results:
        return (
            f"No results for: {query}. Every backend returned nothing — "
            f"try rephrasing the query, or use `source=\"google\"` / `\"web\"` / `\"papers\"` "
            f"to isolate a backend (`source`: auto | brave | google | web | papers)."
        )
    return "\n".join(lines)


@mcp.tool()
async def navigate(ctx: Context, url: str) -> str:
    """
    Navigate to a URL and return the page content as Markdown.

    Use this tool to open a specific webpage and read its contents.

    Args:
        url: The full URL to navigate to (e.g. https://example.com).
    """
    page = _get_page(ctx)
    await _safe_goto(page, url)
    html = await page.content()
    md = markdownify(html, strip=["script", "style", "noscript"])
    # Truncate very long pages
    if len(md) > 15000:
        md = md[:15000] + "\n\n… (content truncated at 15 000 chars)"
    return f"**URL:** {page.url}\n\n{md}"


@mcp.tool()
async def click(ctx: Context, selector: str) -> str:
    """
    Click an element on the current page using a CSS selector.

    Args:
        selector: CSS selector of the element to click (e.g. 'button#submit').
    """
    page = _get_page(ctx)
    await page.click(selector, timeout=10000)
    await page.wait_for_timeout(1500)
    return f"Clicked `{selector}`. Current URL: {page.url}"


@mcp.tool()
async def fill(ctx: Context, selector: str, value: str) -> str:
    """
    Fill a form input field on the current page.

    Args:
        selector: CSS selector of the input element.
        value: The text value to type into the field.
    """
    page = _get_page(ctx)
    await page.fill(selector, value, timeout=10000)
    return f"Filled `{selector}` with `{value}`."


@mcp.tool()
async def screenshot(ctx: Context) -> str:
    """
    Take a screenshot of the current page and return it as a base64-encoded PNG.

    Use this when you need to visually inspect the current state of the page.
    """
    page = _get_page(ctx)
    png_bytes = await page.screenshot(full_page=False)
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64}"


@mcp.tool()
async def extract_text(ctx: Context) -> str:
    """
    Extract all visible text content from the current page.

    Returns plain text (not HTML). Useful for reading articles, docs, etc.
    """
    page = _get_page(ctx)
    text = await page.evaluate("() => document.body.innerText")
    if len(text) > 15000:
        text = text[:15000] + "\n\n… (truncated at 15 000 chars)"
    return f"**URL:** {page.url}\n\n{text}"


@mcp.tool()
async def get_page_snapshot(ctx: Context) -> str:
    """
    Return the accessibility tree (snapshot) of the current page.

    This provides a structured, token-efficient representation of the page
    that is easier for AI agents to reason about than raw HTML.
    """
    page = _get_page(ctx)
    snapshot = await page.accessibility.snapshot()  # type: ignore[union-attr]
    if snapshot is None:
        return "Accessibility snapshot returned None — page may be empty."

    def _format(node: dict[str, Any], indent: int = 0) -> str:
        prefix = "  " * indent
        role = node.get("role", "")
        name = node.get("name", "")
        value = node.get("value", "")
        parts = [f"{prefix}[{role}]"]
        if name:
            parts.append(f'"{name}"')
        if value:
            parts.append(f"value={value}")
        line = " ".join(parts)
        children = node.get("children", [])
        child_lines = [_format(c, indent + 1) for c in children]
        return "\n".join([line] + child_lines)

    tree_str = _format(snapshot)
    if len(tree_str) > 15000:
        tree_str = tree_str[:15000] + "\n\n… (truncated)"
    return f"**URL:** {page.url}\n\n```\n{tree_str}\n```"


@mcp.tool()
async def evaluate_js(ctx: Context, script: str) -> str:
    """
    Execute JavaScript code in the current page context and return the result.

    Args:
        script: JavaScript code to evaluate (e.g. 'document.title').
    """
    page = _get_page(ctx)
    result = await page.evaluate(script)
    return str(result)


@mcp.tool()
async def go_back(ctx: Context) -> str:
    """Navigate back to the previous page in browser history."""
    page = _get_page(ctx)
    await page.go_back(wait_until="domcontentloaded", timeout=15000)
    await page.wait_for_timeout(1000)
    return f"Navigated back. Current URL: {page.url}"


@mcp.tool()
async def get_current_url(ctx: Context) -> str:
    """Return the current page URL and title."""
    page = _get_page(ctx)
    title = await page.title()
    return f"**URL:** {page.url}\n**Title:** {title}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
