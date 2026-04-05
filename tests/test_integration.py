"""
Integration tests — require real API keys and network access.
Run with: pytest -m integration

Skipped by default (see pytest.ini addopts).
"""

import os
import pytest
from pathlib import Path

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_api_keys():
    """Skip all tests in this module unless the necessary keys are present."""
    if not os.getenv("TAVILY_API_KEY"):
        pytest.skip("TAVILY_API_KEY not set")
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")):
        pytest.skip("No LLM API key set (need ANTHROPIC_API_KEY or OPENAI_API_KEY)")


class TestWebSearchIntegration:

    def test_real_search_returns_results(self):
        from tools import web_search
        result = web_search("Python asyncio tutorial")
        assert isinstance(result, str)
        assert len(result) > 100

    async def test_real_fetch_returns_text(self):
        from tools import web_fetch
        result = await web_fetch("https://example.com")
        assert isinstance(result, str)
        assert "Example Domain" in result


class TestPipelineIntegration:

    @pytest.mark.slow
    async def test_full_pipeline_creates_all_files(self, tmp_path):
        """
        Full end-to-end run against real APIs using cheapest models.
        Validates all output files are created and report has meaningful content.
        """
        from pipeline import run_pipeline

        topic_dir = tmp_path / "topics" / "integration-test"
        (topic_dir / "notes").mkdir(parents=True)

        # Use cheapest models to minimise cost
        if os.getenv("ANTHROPIC_API_KEY"):
            model = "claude-haiku-4-5-20251001"
        else:
            model = "gpt-4o-mini"

        await run_pipeline(
            topic="the history of the Python programming language",
            topic_dir=topic_dir,
            models={
                "orchestrator": model,
                "web_researcher": model,
                "fact_checker": model,
                "red_team": model,
            },
            num_researchers=2,  # fewer researchers to reduce cost
        )

        assert (topic_dir / "notes" / "problem-definition.md").exists()
        assert (topic_dir / "notes" / "fact-check.md").exists()
        assert (topic_dir / "notes" / "red-team.md").exists()
        assert (topic_dir / "report.md").exists()

        report = (topic_dir / "report.md").read_text()
        assert len(report) > 500, "Report is unexpectedly short"
