from .tool import Tool
import asyncio
import hashlib
import json
import os
import re
import ipaddress
import concurrent.futures
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_TIMEOUT = 30                 # seconds
DEFAULT_MAX_CHARS = 30000
ABSOLUTE_MAX_CHARS = 200000
DEFAULT_ARTIFACT_DIR = "web_fetch"
DEFAULT_BROWSER_CHANNEL = "chromium"

# ---------------------------------------------------------------------------
# SSRF Protection
# ---------------------------------------------------------------------------
_PRIVATE_BLOCKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _check_ssrf(url_str):
    """Validate URL and block SSRF-vulnerable targets.

    Returns (parsed_url, resolved_ip) on success, or an error dict on failure.
    """
    if not url_str or not isinstance(url_str, str):
        return {"error": "url is required and must be a non-empty string."}

    # Basic URL validation
    parsed = urlparse(url_str)
    if not parsed.scheme:
        return {"error": "URL must include a scheme (e.g. https://)."}
    if parsed.scheme not in ("http", "https"):
        return {"error": f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are allowed."}
    if not parsed.netloc:
        return {"error": f"Invalid URL: no hostname found."}

    hostname = parsed.hostname
    if not hostname:
        return {"error": f"Invalid URL: could not extract hostname."}

    # Resolve hostname to IP
    try:
        import socket
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return {"error": f"Could not resolve hostname: {hostname}"}
    except OSError as e:
        return {"error": f"DNS resolution failed: {e}"}

    if not addr_info:
        return {"error": f"Could not resolve hostname: {hostname}"}

    # Check all resolved addresses against private ranges
    resolved = addr_info[0][4][0]
    try:
        ip = ipaddress.ip_address(resolved)
        for block in _PRIVATE_BLOCKS:
            if ip in block:
                return {"error": f"Blocked SSRF target: {hostname} resolves to private IP {resolved}."}
    except ValueError:
        return {"error": f"Could not parse resolved IP: {resolved}"}

    return (parsed, resolved)


@dataclass
class _FetchedMarkdown:
    markdown: str
    title: str | None = None
    status_code: int | None = None


def _load_web_fetch_config() -> dict:
    """Load web_fetch config from config.yaml, with safe defaults."""
    try:
        from config import load_config
        cfg = load_config()
        return cfg.get("web_fetch", {})
    except Exception:
        return {}


def _coerce_markdown(markdown: Any) -> str:
    """Normalize Crawl4AI markdown objects across versions."""
    if markdown is None:
        return ""
    if isinstance(markdown, str):
        return markdown.strip()
    for attr in ("fit_markdown", "raw_markdown", "markdown"):
        value = getattr(markdown, attr, None)
        if value:
            return str(value).strip()
    return str(markdown).strip()


def _slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "page"
    path = parsed.path.strip("/").replace("/", "-") or "index"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{host}-{path}").strip("-")
    return slug[:80] or "page"


def _line_count(text: str) -> int:
    return text.count("\n") + (1 if text else 0)


# ---------------------------------------------------------------------------
# WebFetch Tool
# ---------------------------------------------------------------------------
class Tool_WebFetch(Tool):
    name: str = "web_fetch"
    description: str = "Fetch a URL with Crawl4AI and return readable markdown."
    stop_event: Any = None
    agent_ref: Any = None
    tool_schema: dict = {
        "name": "web_fetch",
        "description": "Fetches a URL with Crawl4AI and returns clean markdown. "
                       "Full markdown is saved to the filesystem when the output "
                       "is too long, and the response tells you which file to read.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch (must include http:// or https://)."
                },
                "max_chars": {
                    "type": "integer",
                    "description": f"Maximum markdown preview length. Default {DEFAULT_MAX_CHARS}, "
                                   f"capped at {ABSOLUTE_MAX_CHARS}. Full content is saved to a file."
                },
                "timeout": {
                    "type": "integer",
                    "description": f"Request timeout in seconds. Default {DEFAULT_TIMEOUT}."
                }
            },
            "required": ["url"]
        }
    }

    def execute(self, *args, **kwargs):
        url = kwargs.get("url")
        cfg = self._effective_config()
        max_chars = kwargs.get("max_chars", cfg["max_chars"])
        timeout = kwargs.get("timeout", DEFAULT_TIMEOUT)

        checked = _check_ssrf(url)
        if isinstance(checked, dict):
            return checked
        _parsed, resolved_ip = checked

        try:
            fetched = asyncio.run(self._crawl_markdown(url, timeout))
        except ImportError:
            return {
                "error": "web_fetch requires crawl4ai. Install dependencies and run crawl4ai-setup."
            }
        except Exception as e:
            return {"error": f"Failed to fetch URL with Crawl4AI: {e}"}

        body = fetched.markdown.strip()
        if not body:
            return {"error": f"Crawl4AI returned no markdown for {url}."}

        max_chars = min(max(int(max_chars), 1), ABSOLUTE_MAX_CHARS)
        content_file = self._save_markdown(url, body, cfg["artifact_dir"])
        truncated = len(body) > max_chars
        preview = body[:max_chars] if truncated else body

        message = (
            f"web_fetch saved full markdown to {content_file}. "
            f"Returned {len(preview):,} of {len(body):,} chars. "
            f"Use read_file(\"{content_file}\") to read more."
        )

        return {
            "url": url,
            "status_code": fetched.status_code,
            "title": fetched.title,
            "content_type": "text/markdown",
            "content": preview,
            "content_length": len(body),
            "content_file": content_file,
            "resolved_ip": resolved_ip,
            "backend": "crawl4ai",
            "truncated": truncated,
            "message": message,
            "lines": _line_count(body),
        }

    def _effective_config(self) -> dict:
        cfg = _load_web_fetch_config()
        agent_cfg = getattr(getattr(self, "agent_ref", None), "cfg", {})
        if isinstance(agent_cfg, dict):
            cfg = {**cfg, **(agent_cfg.get("web_fetch") or {})}
        return {
            "max_chars": int(cfg.get("max_chars", DEFAULT_MAX_CHARS)),
            "artifact_dir": str(cfg.get("artifact_dir", DEFAULT_ARTIFACT_DIR)),
            "browser_channel": str(cfg.get("browser_channel", DEFAULT_BROWSER_CHANNEL)),
            "respect_robots_txt": bool(cfg.get("respect_robots_txt", True)),
        }

    async def _crawl_markdown(self, url: str, timeout: int) -> _FetchedMarkdown:
        os.environ.setdefault("CRAWL4_AI_BASE_DIRECTORY", str(self._crawl4ai_base_dir()))
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

        cfg = self._effective_config()
        browser_channel = cfg["browser_channel"]
        browser_config = BrowserConfig(
            browser_type="chromium",
            channel=browser_channel,
            chrome_channel=browser_channel,
            headless=True,
            verbose=False,
        )
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            check_robots_txt=cfg["respect_robots_txt"],
        )
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await asyncio.wait_for(
                crawler.arun(url=url, config=run_config),
                timeout=timeout,
            )

        if getattr(result, "success", True) is False:
            error = getattr(result, "error_message", "") or "crawl failed"
            raise RuntimeError(error)

        metadata = getattr(result, "metadata", None) or {}
        title = metadata.get("title") or getattr(result, "title", None)
        return _FetchedMarkdown(
            markdown=_coerce_markdown(getattr(result, "markdown", "")),
            title=title,
            status_code=getattr(result, "status_code", None),
        )

    def _crawl4ai_base_dir(self) -> Path:
        agent = getattr(self, "agent_ref", None)
        project_root = getattr(agent, "_project_root", None)
        if project_root:
            return Path(project_root) / ".temp" / "crawl4ai"
        return Path(__file__).resolve().parents[2] / ".temp" / "crawl4ai"

    def _save_markdown(self, url: str, markdown: str, artifact_dir: str) -> str:
        agent = getattr(self, "agent_ref", None)
        workspace_root = getattr(agent, "_workspace_root", None)
        if workspace_root:
            base_dir = Path(workspace_root) / artifact_dir
        else:
            base_dir = Path(__file__).resolve().parents[2] / ".temp" / artifact_dir
        base_dir.mkdir(parents=True, exist_ok=True)

        digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = base_dir / f"{stamp}-{_slug_from_url(url)}-{digest}.md"
        path.write_text(markdown, encoding="utf-8")
        return str(path)


# ---------------------------------------------------------------------------
# WebSearch Tool
# ---------------------------------------------------------------------------

def _load_search_config():
    """Load web_search config from config.yaml, with defaults."""
    try:
        from config import load_config
        cfg = load_config()
        return cfg.get("web_search", {"backend": "tavily"})
    except Exception:
        return {"backend": "tavily"}


def _search_duckduckgo(query: str, max_results: int = 10) -> list[dict]:
    """Search using DuckDuckGo (free, no API key needed)."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            raise ImportError(
                "DuckDuckGo search requires ddgs or duckduckgo_search. "
                "Run: pip install ddgs"
            )

    results = []
    with DDGS() as ddgs:
        for i, r in enumerate(ddgs.text(query, max_results=max_results)):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })
    return results


def _search_serper(query: str, max_results: int = 10) -> list[dict]:
    """Search using Serper.dev (Google results, requires API key)."""
    cfg = _load_search_config()
    api_key = cfg.get("serper_api_key") or os.environ.get("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Serper backend requires SERPER_API_KEY in config or environment."
        )

    import httpx
    resp = httpx.post(
        "https://google.serper.dev/search",
        json={"q": query, "num": max_results},
        headers={"X-API-KEY": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in data.get("organic", [])[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return results


def _search_tavily(query: str, max_results: int = 10) -> list[dict]:
    """Search using Tavily (AI-native search, requires API key)."""
    cfg = _load_search_config()
    api_key = cfg.get("tavily_api_key") or os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Tavily backend requires TAVILY_API_KEY in config or environment."
        )

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.search(query=query, max_results=max_results)
        results = []
        for item in response.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            })
        return results
    except ImportError:
        raise ImportError(
            "tavily-python is not installed. "
            "Run: pip install tavily-python"
        )


_SEARCH_BACKENDS = {
    "duckduckgo": _search_duckduckgo,
    "serper": _search_serper,
    "tavily": _search_tavily,
}


class Tool_WebSearch(Tool):
    name: str = "web_search"
    description: str = ("Search the web for a query and return structured results "
                        "(title, URL, snippet).")
    stop_event: Any = None
    tool_schema: dict = {
        "name": "web_search",
        "description": "Searches the web and returns a list of results "
                       "with title, URL, and snippet for each. Only use this when you need information in these cases:1.specific version or date involved. 2.current news, events and trends. 3.information you dont't know 4.the user explicitly requires you to do that",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (1-20). "
                                   "Default 10.",
                    "default": 10,
                }
            },
            "required": ["query"]
        }
    }

    def execute(self, *args, **kwargs):
        query = kwargs.get("query")
        max_results = kwargs.get("max_results", 10)

        if not query or not isinstance(query, str):
            return {"error": "query is required and must be a non-empty string."}

        max_results = min(max(max_results, 1), 20)

        cfg = _load_search_config()
        backend = cfg.get("backend", "tavily")

        search_fn = _SEARCH_BACKENDS.get(backend)
        if not search_fn:
            return {"error": f"Unknown search backend '{backend}'. "
                            f"Supported: {', '.join(_SEARCH_BACKENDS)}."}

        try:
            if self.stop_event is not None:
                results = self._run_interruptible(search_fn, query, max_results)
            else:
                results = search_fn(query, max_results)
            return {
                "query": query,
                "results": results,
                "total": len(results),
                "backend": backend,
            }
        except (ImportError, RuntimeError) as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Search failed: {e}"}

    def _run_interruptible(self, search_fn, query, max_results):
        """Run search in a background thread, polling stop_event every 0.5s.

        When the user presses Ctrl+C, ``stop_event`` is set and this method
        stops waiting for the (still-running) background thread, returning an
        empty result list immediately.  The agent's interrupt checkpoint then
        catches ``stop_event`` on the next loop iteration.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(search_fn, query, max_results)
            while True:
                try:
                    return future.result(timeout=0.5)
                except concurrent.futures.TimeoutError:
                    if self.stop_event and self.stop_event.is_set():
                        future.cancel()
                        return []
                    continue
