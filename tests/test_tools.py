import pytest
import respx
import httpx
from unittest.mock import patch, MagicMock


class TestWebSearch:

    def test_returns_string_result(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "Test", "url": "https://example.com", "content": "Test content"}
            ]
        }
        with patch("tools.TavilyClient", return_value=mock_client):
            from tools import web_search
            result = web_search("test query")
        assert isinstance(result, str)
        assert "example.com" in result

    def test_passes_query_to_tavily(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        with patch("tools.TavilyClient", return_value=mock_client):
            from tools import web_search
            web_search("climate change impacts")
        mock_client.search.assert_called_once_with("climate change impacts")

    def test_empty_results_returns_gracefully(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        with patch("tools.TavilyClient", return_value=mock_client):
            from tools import web_search
            result = web_search("obscure query")
        assert isinstance(result, str)

    def test_formats_multiple_results(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "A", "url": "https://a.com", "content": "Content A"},
                {"title": "B", "url": "https://b.com", "content": "Content B"},
            ]
        }
        with patch("tools.TavilyClient", return_value=mock_client):
            from tools import web_search
            result = web_search("query")
        assert "a.com" in result
        assert "b.com" in result

    def test_tavily_api_error_raises(self):
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("API key invalid")
        with patch("tools.TavilyClient", return_value=mock_client):
            from tools import web_search
            with pytest.raises(Exception, match="API key invalid"):
                web_search("query")

    def test_includes_result_content(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "Python Guide", "url": "https://python.org", "content": "Python is great"}
            ]
        }
        with patch("tools.TavilyClient", return_value=mock_client):
            from tools import web_search
            result = web_search("python")
        assert "Python is great" in result


class TestWebFetch:

    @respx.mock
    async def test_fetches_url_and_returns_text(self):
        respx.get("https://example.com/page").mock(
            return_value=httpx.Response(200, text="<html><body><p>Hello world</p></body></html>")
        )
        from tools import web_fetch
        result = await web_fetch("https://example.com/page")
        assert "Hello world" in result

    @respx.mock
    async def test_strips_html_tags(self):
        html = "<html><head><script>alert(1)</script></head><body><p>Clean text</p></body></html>"
        respx.get("https://example.com").mock(return_value=httpx.Response(200, text=html))
        from tools import web_fetch
        result = await web_fetch("https://example.com")
        assert "<" not in result
        assert "Clean text" in result

    @respx.mock
    async def test_strips_script_content(self):
        html = "<html><body><script>var x = 'should not appear';</script><p>Good content</p></body></html>"
        respx.get("https://example.com").mock(return_value=httpx.Response(200, text=html))
        from tools import web_fetch
        result = await web_fetch("https://example.com")
        assert "should not appear" not in result
        assert "Good content" in result

    @respx.mock
    async def test_large_page_is_truncated(self):
        large_html = "<p>" + ("word " * 50_000) + "</p>"
        respx.get("https://example.com/large").mock(
            return_value=httpx.Response(200, text=large_html)
        )
        from tools import web_fetch
        result = await web_fetch("https://example.com/large")
        assert len(result) < 100_000

    @respx.mock
    async def test_returns_string(self):
        respx.get("https://example.com").mock(
            return_value=httpx.Response(200, text="<p>content</p>")
        )
        from tools import web_fetch
        result = await web_fetch("https://example.com")
        assert isinstance(result, str)

    @respx.mock
    async def test_strips_style_content(self):
        html = "<html><head><style>.hidden { display: none; }</style></head><body><p>Visible</p></body></html>"
        respx.get("https://example.com").mock(return_value=httpx.Response(200, text=html))
        from tools import web_fetch
        result = await web_fetch("https://example.com")
        assert "display: none" not in result
        assert "Visible" in result

    @respx.mock
    async def test_http_404_raises(self):
        respx.get("https://example.com/missing").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        from tools import web_fetch
        with pytest.raises(Exception):
            await web_fetch("https://example.com/missing")

    @respx.mock
    async def test_http_500_raises(self):
        respx.get("https://example.com/error").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        from tools import web_fetch
        with pytest.raises(Exception):
            await web_fetch("https://example.com/error")

    async def test_network_error_raises(self):
        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
            from tools import web_fetch
            with pytest.raises(Exception):
                await web_fetch("https://unreachable.example.com")

    @respx.mock
    async def test_plain_text_response_returned(self):
        respx.get("https://example.com/text").mock(
            return_value=httpx.Response(200, text="Just plain text, no HTML.")
        )
        from tools import web_fetch
        result = await web_fetch("https://example.com/text")
        assert "plain text" in result


class TestWebSearchResultFormat:

    def test_result_includes_title(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "My Article Title", "url": "https://example.com", "content": "body"}
            ]
        }
        with patch("tools.TavilyClient", return_value=mock_client):
            from tools import web_search
            result = web_search("query")
        assert "My Article Title" in result

    def test_result_missing_content_field_handled(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "Title", "url": "https://example.com"}
            ]
        }
        with patch("tools.TavilyClient", return_value=mock_client):
            from tools import web_search
            result = web_search("query")
        assert isinstance(result, str)

    def test_results_are_separated(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "First", "url": "https://first.com", "content": "Content 1"},
                {"title": "Second", "url": "https://second.com", "content": "Content 2"},
            ]
        }
        with patch("tools.TavilyClient", return_value=mock_client):
            from tools import web_search
            result = web_search("query")
        # Both results must be present and distinguishable
        assert "Content 1" in result
        assert "Content 2" in result
        assert result.index("Content 1") != result.index("Content 2")
