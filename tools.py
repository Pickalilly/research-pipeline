import os
import re
import httpx
from tavily import TavilyClient


def web_search(query: str) -> str:
    client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))
    response = client.search(query)
    results = response.get("results", [])
    parts = []
    for r in results:
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")
        parts.append(f"Title: {title}\nURL: {url}\nContent: {content}")
    return "\n\n---\n\n".join(parts)


async def web_fetch(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        html = response.text

    # Remove script and style tags along with their content
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Strip all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", html)

    # Truncate to ~50,000 characters
    return text[:50_000]
