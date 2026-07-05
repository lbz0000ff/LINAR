from .tool import Tool
import json
import os
import re
import ipaddress
import concurrent.futures
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_MAX_SIZE = 1024 * 1024       # 1 MB
ABSOLUTE_MAX_SIZE = 5 * 1024 * 1024  # 5 MB hard cap
DEFAULT_TIMEOUT = 30                 # seconds

# Common text-based content types we accept
TEXT_TYPES_PREFIXES = (
    "text/", "application/json", "application/xml", "application/xhtml",
    "application/javascript", "application/x-yaml", "application/x-sh",
    "application/ld+json",
)

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


# ---------------------------------------------------------------------------
# HTML to text conversion — trafilatura → html2text → stdlib fallback
# ---------------------------------------------------------------------------
def _html_to_text(html_content):
    """Convert HTML to clean text using trafilatura (best), html2text, or stdlib."""
    # Level 1: trafilatura — excellent article extraction
    try:
        import trafilatura
        text = trafilatura.extract(
            html_content,
            include_links=True,
            include_images=False,
            include_tables=True,
            output_format="markdown",
            favor_precision=True,
        )
        if text and len(text.strip()) > 50:
            return text.strip()
    except Exception:
        pass

    # Level 2: html2text — full HTML → Markdown
    try:
        import html2text
        h = html2text.HTML2Text()
        h.body_width = 0          # no line wrapping
        h.ignore_links = False
        h.ignore_images = True
        h.ignore_emphasis = False
        h.skip_internal_links = True
        text = h.handle(html_content)
        if text and len(text.strip()) > 0:
            return text.strip()
    except Exception:
        pass

    # Level 3: stdlib strip-tags regex fallback
    text = re.sub(r"<[^>]+>", " ", html_content)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:10000]


def _extract_title(html_content):
    """Extract <title> from HTML (uses trafilatura if available, else regex)."""
    try:
        import trafilatura
        meta = trafilatura.bare_extraction(
            html_content,
            include_links=False,
            include_images=False,
            include_tables=False,
            favor_precision=True,
            output_format="python",
        )
        if meta and meta.get("title"):
            return meta["title"].strip()
    except Exception:
        pass
    m = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# HTTP fetch with fallback chain
# ---------------------------------------------------------------------------
def _fetch_url(url_str, max_size, timeout):
    """Fetch a URL and return (status, headers_dict, content_bytes) or raise."""
    # Try httpx first, then requests, then urllib
    try:
        return _fetch_httpx(url_str, max_size, timeout)
    except ImportError:
        pass

    try:
        return _fetch_requests(url_str, max_size, timeout)
    except ImportError:
        pass

    return _fetch_urllib(url_str, max_size, timeout)


def _fetch_httpx(url_str, max_size, timeout):
    import httpx
    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(timeout),
    ) as client:
        resp = client.get(url_str, headers=_headers())
        resp.raise_for_status()
        content = resp.content[:max_size]
        return resp.status_code, dict(resp.headers), content


def _fetch_requests(url_str, max_size, timeout):
    import requests
    resp = requests.get(
        url_str,
        headers=_headers(),
        timeout=timeout,
        allow_redirects=True,
        stream=True,
    )
    resp.raise_for_status()
    # Stream to respect max_size
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        chunks.append(chunk)
        total += len(chunk)
        if total >= max_size:
            break
    content = b"".join(chunks)[:max_size]
    return resp.status_code, dict(resp.headers), content


def _fetch_urllib(url_str, max_size, timeout):
    import urllib.request
    req = urllib.request.Request(url_str, headers=_headers())
    resp = urllib.request.urlopen(req, timeout=timeout)
    content = resp.read(max_size)
    return resp.status, dict(resp.headers), content


def _headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }


# ---------------------------------------------------------------------------
# Content-type helpers
# ---------------------------------------------------------------------------
def _is_text_content(content_type):
    if not content_type:
        return True  # assume text if no content-type header
    ct = content_type.lower().split(";")[0].strip()
    return ct.startswith(TEXT_TYPES_PREFIXES)


# ---------------------------------------------------------------------------
# WebFetch Tool
# ---------------------------------------------------------------------------
class Tool_WebFetch(Tool):
    name: str = "web_fetch"
    description: str = "Fetch content from a URL and return it as readable text."
    stop_event: Any = None
    tool_schema: dict = {
        "name": "web_fetch",
        "description": "Fetches a URL and returns its content as plain text. "
                       "HTML pages are automatically converted to text. "
                       "Binary content (images, audio, video) is rejected. "
                       "Internal/private IP addresses are blocked for security.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch (must include http:// or https://)."
                },
                "max_size": {
                    "type": "integer",
                    "description": f"Maximum response size in bytes. Default {DEFAULT_MAX_SIZE}, "
                                   f"capped at {ABSOLUTE_MAX_SIZE}."
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
        max_size = kwargs.get("max_size", DEFAULT_MAX_SIZE)
        timeout = kwargs.get("timeout", DEFAULT_TIMEOUT)

        # ── validate URL & SSRF check ──
        checked = _check_ssrf(url)
        if isinstance(checked, dict):
            return checked
        parsed, resolved_ip = checked

        # ── clamp size ──
        max_size = min(max_size, ABSOLUTE_MAX_SIZE)

        # ── fetch ──
        try:
            status, headers, content = _fetch_url(url, max_size, timeout)
        except ImportError as e:
            return {"error": f"No HTTP library available: {e}. Install httpx or requests."}
        except Exception as e:
            msg = str(e)
            # Clean up common verbose error messages
            if hasattr(e, "response") and e.response is not None:
                status_code = e.response.status_code
                msg = f"HTTP {status_code}: {e.response.reason_phrase}"
                if status_code == 404:
                    msg += f" — The URL '{url}' was not found."
                elif status_code == 403:
                    msg += " — Access forbidden."
                elif status_code == 429:
                    msg += " — Rate limited. Try again later."
            return {"error": f"Failed to fetch URL: {msg}"}

        # ── check HTTP status ──
        if status >= 400:
            return {
                "error": f"HTTP {status} error for {url}.",
                "status_code": status,
            }

        # ── check content type ──
        content_type = headers.get("Content-Type") or headers.get("content-type", "")
        if content_type and not _is_text_content(content_type):
            return {
                "error": f"Unsupported content type: '{content_type}'. "
                         f"Only text-based content (HTML, JSON, XML, etc.) is supported.",
                "content_type": content_type,
                "status_code": status,
            }

        # ── decode ──
        # Try charset from Content-Type, then BOM, then fallback to utf-8
        charset = None
        if content_type:
            m = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
            if m:
                charset = m.group(1)

        if not charset:
            # Check for BOM
            if content[:3] == b"\xef\xbb\xbf":
                charset = "utf-8-sig"
            elif content[:2] == b"\xff\xfe":
                charset = "utf-16-le"
            elif content[:2] == b"\xfe\xff":
                charset = "utf-16-be"

        if charset:
            try:
                text = content.decode(charset, errors="replace")
            except LookupError:
                text = content.decode("utf-8", errors="replace")
        else:
            text = content.decode("utf-8", errors="replace")

        # ── convert HTML to text ──
        is_html = "html" in content_type.lower() if content_type else False
        title = None
        if is_html:
            title = _extract_title(text)
            body = _html_to_text(text)
        else:
            body = text.strip()

        # ── build result ──
        result = {
            "url": url,
            "status_code": status,
            "content_type": content_type,
            "content": body,
            "content_length": len(body),
            "resolved_ip": resolved_ip,
        }

        if title:
            result["title"] = title

        # Warn if content was truncated
        if len(content) >= max_size:
            result["truncated"] = True

        return result


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
