import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Chunk builders ──────────────────────────────────────────────────────────

def make_text_chunk(content: str) -> MagicMock:
    """A streamed text delta chunk."""
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = content
    chunk.choices[0].delta.tool_calls = None
    return chunk


def make_tool_call_chunk(index: int, name: str | None, arguments_fragment: str) -> MagicMock:
    """
    A streamed tool-call delta chunk.

    LiteLLM streams tool calls across multiple chunks:
    - First chunk carries the function name and the start of arguments
    - Subsequent chunks carry None for name and more argument fragments
    """
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = None
    tc = MagicMock()
    tc.index = index
    tc.id = f"call_{index}"
    tc.function.name = name
    tc.function.arguments = arguments_fragment
    chunk.choices[0].delta.tool_calls = [tc]
    return chunk


def make_finish_chunk() -> MagicMock:
    """The final chunk with no content."""
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = None
    chunk.choices[0].delta.tool_calls = None
    return chunk


# ── Async iterator / context manager ────────────────────────────────────────

class AsyncChunkIterator:
    """
    Wraps a list of chunks as both an async iterator and async context manager,
    matching the exact interface of litellm.acompletion(stream=True).
    """

    def __init__(self, chunks: list):
        self._chunks = chunks

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for chunk in self._chunks:
            yield chunk

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ── Response factories ───────────────────────────────────────────────────────

def text_response(text: str) -> AsyncChunkIterator:
    """
    Simulate a pure-text streaming response.
    Splits text into per-word chunks to exercise the token accumulation path.
    """
    chunks = [make_text_chunk(word + " ") for word in text.split()]
    chunks.append(make_finish_chunk())
    return AsyncChunkIterator(chunks)


def tool_call_then_text_response(
    tool_name: str,
    tool_args: dict,
    final_text: str,
) -> list[AsyncChunkIterator]:
    """
    Returns a list of two AsyncChunkIterators — one per acompletion call:
    1. The model returns a tool call (arguments deliberately split across two chunks)
    2. After the tool result is injected, the model returns the final text

    Splitting arguments across chunks catches the common bug where the loop
    assumes one chunk = one complete tool call.
    """
    args_str = json.dumps(tool_args)
    mid = max(1, len(args_str) // 2)

    turn1_chunks = [
        make_tool_call_chunk(0, tool_name, args_str[:mid]),
        make_tool_call_chunk(0, None, args_str[mid:]),
        make_finish_chunk(),
    ]
    turn2_chunks = [make_text_chunk(final_text), make_finish_chunk()]

    return [AsyncChunkIterator(turn1_chunks), AsyncChunkIterator(turn2_chunks)]


def multi_tool_call_response(
    tool_calls: list[tuple[str, dict]],
    final_text: str,
) -> list[AsyncChunkIterator]:
    """
    First response contains multiple parallel tool calls (different indices).
    Second response is the final text after all tool results are injected.
    """
    turn1_chunks = []
    for i, (name, args) in enumerate(tool_calls):
        turn1_chunks.append(make_tool_call_chunk(i, name, json.dumps(args)))
    turn1_chunks.append(make_finish_chunk())

    turn2_chunks = [make_text_chunk(final_text), make_finish_chunk()]

    return [AsyncChunkIterator(turn1_chunks), AsyncChunkIterator(turn2_chunks)]


# ── pytest fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def mock_acompletion(monkeypatch):
    """
    Returns a configure function. Call it with a list of AsyncChunkIterators
    (one per acompletion call the agent will make).

    Usage:
        def test_something(mock_acompletion):
            mock = mock_acompletion([text_response("Hello world")])
            # run agent ...
            assert mock.call_count == 1
    """
    responses_queue: list[AsyncChunkIterator] = []
    call_count_holder = [0]

    async def fake_acompletion(*args, **kwargs):
        idx = call_count_holder[0]
        if idx >= len(responses_queue):
            raise RuntimeError(
                f"acompletion called {idx + 1} times but only "
                f"{len(responses_queue)} responses were queued"
            )
        call_count_holder[0] += 1
        return responses_queue[idx]

    mock = AsyncMock(side_effect=fake_acompletion)

    def configure(responses: list[AsyncChunkIterator]):
        responses_queue.clear()
        responses_queue.extend(responses)
        call_count_holder[0] = 0
        monkeypatch.setattr("litellm.acompletion", mock)
        return mock

    return configure


@pytest.fixture
def tmp_topic_dir(tmp_path):
    """
    Creates the standard topic directory structure under pytest's tmp_path.
    Returns the topic root Path.
    """
    topic_dir = tmp_path / "topics" / "test-topic"
    (topic_dir / "notes").mkdir(parents=True)
    return topic_dir


@pytest.fixture
def agent_prompts_dir(tmp_path):
    """
    Creates a .claude/agents/ directory with minimal stub agent prompts.
    Returns the agents dir Path.
    """
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)

    stubs = {
        "web-researcher.md": "---\nname: web-researcher\n---\nYou are a web researcher. Research the given sub-question.",
        "fact-checker.md": "---\nname: fact-checker\n---\nYou are a fact checker. Verify claims in the notes.",
        "red-team.md": "---\nname: red-team\n---\nYou are a red team agent. Challenge the findings.",
        "research-orchestrator.md": "---\nname: research-orchestrator\n---\nYou are a research orchestrator.",
    }
    for filename, content in stubs.items():
        (agents_dir / filename).write_text(content)

    return agents_dir
