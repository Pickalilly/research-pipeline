import asyncio
import json
import pytest
from pathlib import Path

from tests.conftest import (
    text_response,
    tool_call_then_text_response,
    multi_tool_call_response,
)


# ════════════════════════════════════════════════════════════════════════════
# run_agent — simple text response
# ════════════════════════════════════════════════════════════════════════════

class TestRunAgentTextResponse:

    async def test_returns_text_content(self, mock_acompletion, tmp_topic_dir):
        mock_acompletion([text_response("The answer is 42.")])
        from pipeline import run_agent
        result = await run_agent(
            system_prompt="You are helpful.",
            user_message="What is the answer?",
            model="claude-haiku-4-5",
            tools=[],
            output_path=tmp_topic_dir / "notes" / "output.md",
        )
        assert "42" in result

    async def test_writes_output_to_file(self, mock_acompletion, tmp_topic_dir):
        mock_acompletion([text_response("Findings about the topic.")])
        from pipeline import run_agent
        output_path = tmp_topic_dir / "notes" / "output.md"
        await run_agent(
            system_prompt="You are helpful.",
            user_message="Research something.",
            model="claude-haiku-4-5",
            tools=[],
            output_path=output_path,
        )
        assert output_path.exists()
        assert "Findings" in output_path.read_text()

    async def test_on_token_callback_fires_for_each_chunk(self, mock_acompletion, tmp_topic_dir):
        mock_acompletion([text_response("Hello world foo")])
        from pipeline import run_agent
        received_tokens = []

        await run_agent(
            system_prompt="",
            user_message="Say hello",
            model="gpt-4o-mini",
            tools=[],
            output_path=tmp_topic_dir / "notes" / "out.md",
            on_token=lambda t: received_tokens.append(t),
        )
        assert len(received_tokens) >= 3
        assert "".join(received_tokens).strip() == "Hello world foo"

    async def test_on_token_is_optional(self, mock_acompletion, tmp_topic_dir):
        mock_acompletion([text_response("Result")])
        from pipeline import run_agent
        # Should not raise when on_token is omitted
        await run_agent(
            system_prompt="",
            user_message="Go",
            model="gpt-4o-mini",
            tools=[],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )

    async def test_passes_correct_model_to_acompletion(self, mock_acompletion, tmp_topic_dir):
        mock = mock_acompletion([text_response("OK")])
        from pipeline import run_agent
        await run_agent(
            system_prompt="",
            user_message="Go",
            model="claude-sonnet-4-6",
            tools=[],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )
        call_kwargs = mock.call_args.kwargs
        assert call_kwargs.get("model") == "claude-sonnet-4-6"

    async def test_passes_system_prompt_in_messages(self, mock_acompletion, tmp_topic_dir):
        mock = mock_acompletion([text_response("OK")])
        from pipeline import run_agent
        await run_agent(
            system_prompt="You are a specialized agent.",
            user_message="Do something.",
            model="gpt-4o-mini",
            tools=[],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )
        messages = mock.call_args.kwargs["messages"]
        system_messages = [m for m in messages if m.get("role") == "system"]
        assert any("specialized agent" in m.get("content", "") for m in system_messages)


# ════════════════════════════════════════════════════════════════════════════
# run_agent — single tool call → result → final text
# ════════════════════════════════════════════════════════════════════════════

class TestRunAgentSingleToolCall:

    async def test_executes_tool_and_feeds_result_back(
        self, mock_acompletion, tmp_topic_dir, mocker
    ):
        responses = tool_call_then_text_response(
            tool_name="web_search",
            tool_args={"query": "climate change"},
            final_text="Based on search results, climate is changing.",
        )
        mock_acompletion(responses)
        mock_search = mocker.patch("pipeline.web_search", return_value="Search result: CO2 rising")

        from pipeline import run_agent
        result = await run_agent(
            system_prompt="",
            user_message="Research climate",
            model="claude-haiku-4-5",
            tools=["web_search"],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )
        mock_search.assert_called_once_with(query="climate change")
        assert "climate is changing" in result

    async def test_tool_result_injected_into_second_call(
        self, mock_acompletion, tmp_topic_dir, mocker
    ):
        responses = tool_call_then_text_response(
            tool_name="web_search",
            tool_args={"query": "test"},
            final_text="Final answer",
        )
        mock = mock_acompletion(responses)
        mocker.patch("pipeline.web_search", return_value="TOOL_RESULT_CONTENT")

        from pipeline import run_agent
        await run_agent(
            system_prompt="",
            user_message="Search for test",
            model="gpt-4o-mini",
            tools=["web_search"],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )
        # Second call's messages must contain the tool result
        second_call_messages = mock.call_args_list[1].kwargs["messages"]
        messages_str = str(second_call_messages)
        assert "TOOL_RESULT_CONTENT" in messages_str

    async def test_arguments_accumulated_across_chunks(
        self, mock_acompletion, tmp_topic_dir, mocker
    ):
        """
        Regression: tool arguments stream in fragments.
        The loop must concatenate all fragments before calling json.loads().
        tool_call_then_text_response deliberately splits the JSON args string.
        """
        responses = tool_call_then_text_response(
            tool_name="web_search",
            tool_args={"query": "a very long search query string"},
            final_text="Done",
        )
        mock_acompletion(responses)
        mock_search = mocker.patch("pipeline.web_search", return_value="result")

        from pipeline import run_agent
        await run_agent(
            system_prompt="",
            user_message="Go",
            model="gpt-4o-mini",
            tools=["web_search"],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )
        mock_search.assert_called_once_with(query="a very long search query string")

    async def test_makes_exactly_two_acompletion_calls(
        self, mock_acompletion, tmp_topic_dir, mocker
    ):
        responses = tool_call_then_text_response(
            tool_name="web_search",
            tool_args={"query": "q"},
            final_text="Answer",
        )
        mock = mock_acompletion(responses)
        mocker.patch("pipeline.web_search", return_value="result")

        from pipeline import run_agent
        await run_agent(
            system_prompt="",
            user_message="Go",
            model="gpt-4o-mini",
            tools=["web_search"],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )
        assert mock.call_count == 2


# ════════════════════════════════════════════════════════════════════════════
# run_agent — multiple tool calls in one response
# ════════════════════════════════════════════════════════════════════════════

class TestRunAgentMultipleToolCalls:

    async def test_all_tools_called(self, mock_acompletion, tmp_topic_dir, mocker):
        responses = multi_tool_call_response(
            tool_calls=[
                ("web_search", {"query": "first query"}),
                ("web_search", {"query": "second query"}),
            ],
            final_text="Synthesized answer.",
        )
        mock_acompletion(responses)
        mock_search = mocker.patch("pipeline.web_search", return_value="result")

        from pipeline import run_agent
        await run_agent(
            system_prompt="",
            user_message="Search twice",
            model="gpt-4o-mini",
            tools=["web_search"],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )
        assert mock_search.call_count == 2

    async def test_all_tool_results_injected_before_second_turn(
        self, mock_acompletion, tmp_topic_dir, mocker
    ):
        responses = multi_tool_call_response(
            tool_calls=[
                ("web_search", {"query": "q1"}),
                ("web_fetch", {"url": "https://example.com"}),
            ],
            final_text="Answer",
        )
        mock = mock_acompletion(responses)
        mocker.patch("pipeline.web_search", return_value="SEARCH_RESULT")
        mocker.patch("pipeline.web_fetch", return_value="FETCH_RESULT")

        from pipeline import run_agent
        await run_agent(
            system_prompt="",
            user_message="Go",
            model="gpt-4o-mini",
            tools=["web_search", "web_fetch"],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )
        second_call_messages = mock.call_args_list[1].kwargs["messages"]
        messages_str = str(second_call_messages)
        assert "SEARCH_RESULT" in messages_str
        assert "FETCH_RESULT" in messages_str


# ════════════════════════════════════════════════════════════════════════════
# run_pipeline — file creation
# ════════════════════════════════════════════════════════════════════════════

class TestRunPipelineFileCreation:

    @pytest.fixture
    def pipeline_mocks(self, mock_acompletion, agent_prompts_dir, mocker):
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))
        responses = [text_response(f"Response {i}") for i in range(20)]
        mock_acompletion(responses)

    async def test_creates_problem_definition(self, pipeline_mocks, tmp_topic_dir):
        from pipeline import run_pipeline
        await run_pipeline(
            topic="test topic",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "gpt-4o", "web_researcher": "gpt-4o-mini",
                    "fact_checker": "gpt-4o-mini", "red_team": "gpt-4o"},
        )
        assert (tmp_topic_dir / "notes" / "problem-definition.md").exists()

    async def test_creates_fact_check_file(self, pipeline_mocks, tmp_topic_dir):
        from pipeline import run_pipeline
        await run_pipeline(
            topic="test topic",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "gpt-4o", "web_researcher": "gpt-4o-mini",
                    "fact_checker": "gpt-4o-mini", "red_team": "gpt-4o"},
        )
        assert (tmp_topic_dir / "notes" / "fact-check.md").exists()

    async def test_creates_red_team_file(self, pipeline_mocks, tmp_topic_dir):
        from pipeline import run_pipeline
        await run_pipeline(
            topic="test topic",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "gpt-4o", "web_researcher": "gpt-4o-mini",
                    "fact_checker": "gpt-4o-mini", "red_team": "gpt-4o"},
        )
        assert (tmp_topic_dir / "notes" / "red-team.md").exists()

    async def test_creates_report(self, pipeline_mocks, tmp_topic_dir):
        from pipeline import run_pipeline
        await run_pipeline(
            topic="test topic",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "gpt-4o", "web_researcher": "gpt-4o-mini",
                    "fact_checker": "gpt-4o-mini", "red_team": "gpt-4o"},
        )
        assert (tmp_topic_dir / "report.md").exists()

    async def test_creates_log_file(self, pipeline_mocks, tmp_topic_dir):
        from pipeline import run_pipeline
        await run_pipeline(
            topic="test topic",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "gpt-4o", "web_researcher": "gpt-4o-mini",
                    "fact_checker": "gpt-4o-mini", "red_team": "gpt-4o"},
        )
        assert (tmp_topic_dir / "notes" / "log.md").exists()


# ════════════════════════════════════════════════════════════════════════════
# run_pipeline — parallelism verification
# ════════════════════════════════════════════════════════════════════════════

class TestResearcherParallelism:
    """
    Verify researchers run concurrently via asyncio.gather(), not sequentially.

    Each researcher sleeps for 0.1s.
    - Sequential: total ≈ N * 0.1s
    - Parallel:   total ≈ 0.1s

    This catches regressions where asyncio.gather() is replaced with a for loop.
    """

    async def test_researchers_run_in_parallel(self, agent_prompts_dir, mocker):
        SLEEP = 0.1
        NUM_RESEARCHERS = 3
        SEQUENTIAL_THRESHOLD = SLEEP * NUM_RESEARCHERS * 0.8

        call_start_times = []

        async def fake_run_agent(*, agent_role=None, **kwargs):
            if agent_role == "web_researcher":
                call_start_times.append(asyncio.get_event_loop().time())
                await asyncio.sleep(SLEEP)
            return f"Output for {agent_role}"

        mocker.patch("pipeline.run_agent", side_effect=fake_run_agent)
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))

        from pipeline import run_pipeline
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            topic_dir = Path(tmpdir) / "topics" / "parallel-test"
            (topic_dir / "notes").mkdir(parents=True)

            start = asyncio.get_event_loop().time()
            await run_pipeline(
                topic="parallelism test",
                topic_dir=topic_dir,
                models={"orchestrator": "gpt-4o", "web_researcher": "gpt-4o-mini",
                        "fact_checker": "gpt-4o-mini", "red_team": "gpt-4o"},
                num_researchers=NUM_RESEARCHERS,
            )
            elapsed = asyncio.get_event_loop().time() - start

        assert len(call_start_times) == NUM_RESEARCHERS, (
            f"Expected {NUM_RESEARCHERS} researcher calls, got {len(call_start_times)}"
        )
        time_spread = max(call_start_times) - min(call_start_times)
        assert time_spread < SLEEP * 0.5, (
            f"Researchers started {time_spread:.3f}s apart — looks sequential, not parallel"
        )
        assert elapsed < SEQUENTIAL_THRESHOLD, (
            f"Total time {elapsed:.3f}s >= sequential threshold {SEQUENTIAL_THRESHOLD:.3f}s"
        )


# ════════════════════════════════════════════════════════════════════════════
# run_pipeline — model routing
# ════════════════════════════════════════════════════════════════════════════

class TestModelRouting:

    async def test_correct_models_used_for_each_role(
        self, mock_acompletion, agent_prompts_dir, mocker, tmp_topic_dir
    ):
        mock = mock_acompletion([text_response(f"R{i}") for i in range(20)])
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))

        from pipeline import run_pipeline
        await run_pipeline(
            topic="test",
            topic_dir=tmp_topic_dir,
            models={
                "orchestrator": "ORCH_MODEL",
                "web_researcher": "RESEARCHER_MODEL",
                "fact_checker": "FACTCHECK_MODEL",
                "red_team": "REDTEAM_MODEL",
            },
        )
        all_models = [c.kwargs["model"] for c in mock.call_args_list]
        assert "RESEARCHER_MODEL" in all_models
        assert "FACTCHECK_MODEL" in all_models
        assert "REDTEAM_MODEL" in all_models
        assert "ORCH_MODEL" in all_models


# ════════════════════════════════════════════════════════════════════════════
# run_agent — web_fetch tool
# ════════════════════════════════════════════════════════════════════════════

class TestRunAgentWebFetchTool:

    async def test_web_fetch_tool_called_with_url(
        self, mock_acompletion, tmp_topic_dir, mocker
    ):
        responses = tool_call_then_text_response(
            tool_name="web_fetch",
            tool_args={"url": "https://example.com/article"},
            final_text="The article says something interesting.",
        )
        mock_acompletion(responses)
        mock_fetch = mocker.patch("pipeline.web_fetch", return_value="Article text content")

        from pipeline import run_agent
        result = await run_agent(
            system_prompt="",
            user_message="Fetch and summarise the article.",
            model="claude-haiku-4-5",
            tools=["web_fetch"],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )
        mock_fetch.assert_called_once_with(url="https://example.com/article")
        assert "interesting" in result

    async def test_web_fetch_result_injected_into_second_call(
        self, mock_acompletion, tmp_topic_dir, mocker
    ):
        responses = tool_call_then_text_response(
            tool_name="web_fetch",
            tool_args={"url": "https://example.com"},
            final_text="Summary done.",
        )
        mock = mock_acompletion(responses)
        mocker.patch("pipeline.web_fetch", return_value="FETCHED_PAGE_CONTENT")

        from pipeline import run_agent
        await run_agent(
            system_prompt="",
            user_message="Fetch the page.",
            model="gpt-4o-mini",
            tools=["web_fetch"],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )
        second_call_messages = mock.call_args_list[1].kwargs["messages"]
        assert "FETCHED_PAGE_CONTENT" in str(second_call_messages)


# ════════════════════════════════════════════════════════════════════════════
# run_agent — sequential multi-round tool calls
# ════════════════════════════════════════════════════════════════════════════

class TestRunAgentSequentialToolRounds:
    """
    The agent may call tools across multiple turns, not just one:
    turn 1 → tool call A → turn 2 → tool call B → turn 3 → final text.
    """

    async def test_two_sequential_tool_rounds(
        self, mock_acompletion, tmp_topic_dir, mocker
    ):
        from tests.conftest import AsyncChunkIterator, make_tool_call_chunk, make_finish_chunk, make_text_chunk

        round1 = AsyncChunkIterator([
            make_tool_call_chunk(0, "web_search", json.dumps({"query": "first"})),
            make_finish_chunk(),
        ])
        round2 = AsyncChunkIterator([
            make_tool_call_chunk(0, "web_search", json.dumps({"query": "second"})),
            make_finish_chunk(),
        ])
        round3 = AsyncChunkIterator([make_text_chunk("Final answer."), make_finish_chunk()])

        mock_acompletion([round1, round2, round3])
        mock_search = mocker.patch("pipeline.web_search", return_value="search result")

        from pipeline import run_agent
        result = await run_agent(
            system_prompt="",
            user_message="Search twice sequentially.",
            model="gpt-4o-mini",
            tools=["web_search"],
            output_path=tmp_topic_dir / "notes" / "out.md",
        )
        assert mock_search.call_count == 2
        assert "Final answer" in result


# ════════════════════════════════════════════════════════════════════════════
# run_pipeline — num_researchers parameter
# ════════════════════════════════════════════════════════════════════════════

class TestRunPipelineNumResearchers:

    @pytest.mark.parametrize("num_researchers", [1, 2, 5])
    async def test_correct_number_of_researcher_calls(
        self, num_researchers, mock_acompletion, agent_prompts_dir, mocker, tmp_topic_dir
    ):
        researcher_calls = []

        async def fake_run_agent(*, agent_role=None, **kwargs):
            if agent_role == "web_researcher":
                researcher_calls.append(True)
            return "output"

        mocker.patch("pipeline.run_agent", side_effect=fake_run_agent)
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))

        from pipeline import run_pipeline
        await run_pipeline(
            topic="test",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "m", "web_researcher": "m",
                    "fact_checker": "m", "red_team": "m"},
            num_researchers=num_researchers,
        )
        assert len(researcher_calls) == num_researchers

    async def test_default_num_researchers_is_reasonable(
        self, mock_acompletion, agent_prompts_dir, mocker, tmp_topic_dir
    ):
        researcher_calls = []

        async def fake_run_agent(*, agent_role=None, **kwargs):
            if agent_role == "web_researcher":
                researcher_calls.append(True)
            return "output"

        mocker.patch("pipeline.run_agent", side_effect=fake_run_agent)
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))

        from pipeline import run_pipeline
        await run_pipeline(
            topic="test",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "m", "web_researcher": "m",
                    "fact_checker": "m", "red_team": "m"},
        )
        assert 1 <= len(researcher_calls) <= 10


# ════════════════════════════════════════════════════════════════════════════
# run_pipeline — content flow between stages
# ════════════════════════════════════════════════════════════════════════════

class TestRunPipelineContentFlow:
    """
    Verify that outputs from early pipeline stages are available to later stages.
    The problem definition must reach researchers; researcher notes must reach
    fact-checker and red-team; all notes must reach the final report agent.
    """

    async def test_problem_definition_passed_to_researchers(
        self, agent_prompts_dir, mocker, tmp_topic_dir
    ):
        call_log = []

        async def fake_run_agent(*, agent_role=None, user_message="", **kwargs):
            call_log.append((agent_role, user_message))
            return f"Output of {agent_role}"

        mocker.patch("pipeline.run_agent", side_effect=fake_run_agent)
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))

        from pipeline import run_pipeline
        await run_pipeline(
            topic="test topic",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "m", "web_researcher": "m",
                    "fact_checker": "m", "red_team": "m"},
            num_researchers=1,
        )

        researcher_calls = [(role, msg) for role, msg in call_log if role == "web_researcher"]
        assert researcher_calls, "No researcher calls found"
        # The researcher's user_message should reference the problem definition output
        combined = " ".join(msg for _, msg in researcher_calls)
        assert "Output of orchestrator" in combined or "problem-definition" in combined or "Output of" in combined

    async def test_research_notes_passed_to_fact_checker(
        self, agent_prompts_dir, mocker, tmp_topic_dir
    ):
        call_log = []

        async def fake_run_agent(*, agent_role=None, user_message="", output_path=None, **kwargs):
            content = f"Findings from {agent_role}"
            if output_path is not None:
                output_path.write_text(content)
            call_log.append((agent_role, user_message))
            return content

        mocker.patch("pipeline.run_agent", side_effect=fake_run_agent)
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))

        from pipeline import run_pipeline
        await run_pipeline(
            topic="test topic",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "m", "web_researcher": "m",
                    "fact_checker": "m", "red_team": "m"},
            num_researchers=2,
        )

        fact_checker_calls = [(role, msg) for role, msg in call_log if role == "fact_checker"]
        assert fact_checker_calls, "No fact-checker call found"
        fact_checker_input = fact_checker_calls[0][1]
        # Fact checker must see researcher output — either inline or via file path
        assert "web_researcher" in fact_checker_input or "Findings from" in fact_checker_input or "notes" in fact_checker_input

    async def test_report_written_to_correct_path(
        self, mock_acompletion, agent_prompts_dir, mocker, tmp_topic_dir
    ):
        mock_acompletion([text_response(f"Stage {i}") for i in range(20)])
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))

        from pipeline import run_pipeline
        await run_pipeline(
            topic="test topic",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "m", "web_researcher": "m",
                    "fact_checker": "m", "red_team": "m"},
        )
        report_path = tmp_topic_dir / "report.md"
        assert report_path.exists()
        assert len(report_path.read_text()) > 0


# ════════════════════════════════════════════════════════════════════════════
# run_pipeline — on_token callback propagation
# ════════════════════════════════════════════════════════════════════════════

class TestRunPipelineOnToken:

    async def test_on_token_receives_tokens_from_pipeline(
        self, mock_acompletion, agent_prompts_dir, mocker, tmp_topic_dir
    ):
        mock_acompletion([text_response(f"Stage {i} text") for i in range(20)])
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))

        tokens = []

        from pipeline import run_pipeline
        await run_pipeline(
            topic="test topic",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "m", "web_researcher": "m",
                    "fact_checker": "m", "red_team": "m"},
            on_token=lambda t: tokens.append(t),
        )
        assert len(tokens) > 0

    async def test_on_token_is_optional_at_pipeline_level(
        self, mock_acompletion, agent_prompts_dir, mocker, tmp_topic_dir
    ):
        mock_acompletion([text_response(f"Stage {i}") for i in range(20)])
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))

        from pipeline import run_pipeline
        # Should not raise when on_token is omitted
        await run_pipeline(
            topic="test topic",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "m", "web_researcher": "m",
                    "fact_checker": "m", "red_team": "m"},
        )


# ════════════════════════════════════════════════════════════════════════════
# run_pipeline — log file content
# ════════════════════════════════════════════════════════════════════════════

class TestRunPipelineLogFile:

    async def test_log_file_records_pipeline_stages(
        self, mock_acompletion, agent_prompts_dir, mocker, tmp_topic_dir
    ):
        mock_acompletion([text_response(f"Output {i}") for i in range(20)])
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))

        from pipeline import run_pipeline
        await run_pipeline(
            topic="test topic",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "m", "web_researcher": "m",
                    "fact_checker": "m", "red_team": "m"},
        )
        log = (tmp_topic_dir / "notes" / "log.md").read_text()
        assert len(log) > 0

    async def test_log_file_contains_topic(
        self, mock_acompletion, agent_prompts_dir, mocker, tmp_topic_dir
    ):
        mock_acompletion([text_response(f"Output {i}") for i in range(20)])
        mocker.patch("pipeline.AGENTS_DIR", str(agent_prompts_dir))

        from pipeline import run_pipeline
        await run_pipeline(
            topic="quantum computing",
            topic_dir=tmp_topic_dir,
            models={"orchestrator": "m", "web_researcher": "m",
                    "fact_checker": "m", "red_team": "m"},
        )
        log = (tmp_topic_dir / "notes" / "log.md").read_text()
        assert "quantum computing" in log
