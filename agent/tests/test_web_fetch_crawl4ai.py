import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tool.basic_tools import tool_web
from tool.basic_tools.tool_web import Tool_WebFetch


def test_web_fetch_truncates_preview_and_saves_full_markdown(monkeypatch, tmp_path):
    async def fake_crawl_markdown(self, url, timeout):
        return tool_web._FetchedMarkdown(
            markdown="0123456789abcdef",
            title="Example",
            status_code=200,
        )

    monkeypatch.setattr(Tool_WebFetch, "_crawl_markdown", fake_crawl_markdown, raising=False)

    tool = Tool_WebFetch()
    tool.agent_ref = SimpleNamespace(
        _workspace_root=str(tmp_path),
        cfg={"web_fetch": {"max_chars": 10}},
    )

    result = tool.execute(url="https://example.com/article")

    assert result["backend"] == "crawl4ai"
    assert result["title"] == "Example"
    assert result["content"] == "0123456789"
    assert result["content_length"] == 16
    assert result["truncated"] is True
    assert result["content_file"].endswith(".md")
    assert os.path.exists(result["content_file"])
    with open(result["content_file"], encoding="utf-8") as f:
        assert f.read() == "0123456789abcdef"
    assert 'read_file("' in result["message"]
    assert result["content_file"] in result["message"]


def test_web_fetch_uses_configured_browser_channel_and_bypasses_cache(monkeypatch):
    seen = {}
    browser_seen = {}

    class FakeCacheMode:
        BYPASS = "bypass"

    class FakeBrowserConfig:
        def __init__(self, **kwargs):
            browser_seen.update(kwargs)

    class FakeCrawlerRunConfig:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    class FakeCrawler:
        def __init__(self, config=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def arun(self, url, config=None):
            return SimpleNamespace(
                success=True,
                markdown="ok",
                metadata={"title": "OK"},
                status_code=200,
            )

    fake_module = SimpleNamespace(
        AsyncWebCrawler=FakeCrawler,
        BrowserConfig=FakeBrowserConfig,
        CacheMode=FakeCacheMode,
        CrawlerRunConfig=FakeCrawlerRunConfig,
    )
    monkeypatch.setitem(sys.modules, "crawl4ai", fake_module)

    tool = Tool_WebFetch()
    result = __import__("asyncio").run(tool._crawl_markdown("https://example.com", 5))

    assert result.markdown == "ok"
    assert browser_seen["channel"] == "chromium"
    assert browser_seen["chrome_channel"] == "chromium"
    assert seen["cache_mode"] == FakeCacheMode.BYPASS
    assert seen["check_robots_txt"] is True


def test_web_fetch_can_override_browser_channel_from_agent_config(monkeypatch):
    seen = {}

    class FakeCacheMode:
        BYPASS = "bypass"

    class FakeBrowserConfig:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    class FakeCrawlerRunConfig:
        def __init__(self, **kwargs):
            pass

    class FakeCrawler:
        def __init__(self, config=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def arun(self, url, config=None):
            return SimpleNamespace(success=True, markdown="ok", metadata={}, status_code=200)

    monkeypatch.setitem(
        sys.modules,
        "crawl4ai",
        SimpleNamespace(
            AsyncWebCrawler=FakeCrawler,
            BrowserConfig=FakeBrowserConfig,
            CacheMode=FakeCacheMode,
            CrawlerRunConfig=FakeCrawlerRunConfig,
        ),
    )

    tool = Tool_WebFetch()
    tool.agent_ref = SimpleNamespace(cfg={"web_fetch": {"browser_channel": "msedge"}})
    __import__("asyncio").run(tool._crawl_markdown("https://example.com", 5))

    assert seen["channel"] == "msedge"
    assert seen["chrome_channel"] == "msedge"
