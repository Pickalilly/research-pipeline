import asyncio
import json
from pathlib import Path

import litellm

from tools import web_search, web_fetch

AGENTS_DIR = ".claude/agents"

# Tool definitions passed to litellm
TOOL_DEFINITIONS = {
    "web_search": {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."},
                },
                "required": ["query"],
            },
        },
    },
    "web_fetch": {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and return the text content of a web page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch."},
                },
                "required": ["url"],
            },
        },
    },
}


def _load_agent_prompt(agent_filename: str) -> str:
    """Load agent system prompt, stripping YAML frontmatter."""
    path = Path(AGENTS_DIR) / agent_filename
    text = path.read_text()
    lines = text.splitlines()

    # Strip YAML frontmatter between --- delimiters
    if lines and lines[0].strip() == "---":
        end = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end = i
                break
        if end is not None:
            lines = lines[end + 1:]

    return "\n".join(lines).strip()


async def run_agent(
    *,
    system_prompt: str,
    user_message: str,
    model: str,
    tools: list,
    output_path: Path,
    on_token: callable = None,
    agent_role: str = None,
) -> str:
    """Run an agent with optional tool use, streaming tokens, and file output."""

    tool_defs = [TOOL_DEFINITIONS[t] for t in tools if t in TOOL_DEFINITIONS]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    while True:
        kwargs = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs

        response = await litellm.acompletion(**kwargs)

        # Accumulate text and tool calls across chunks
        text_parts = []
        # tool_calls_by_index: {index: {"id": ..., "name": ..., "arguments": ...}}
        tool_calls_by_index = {}

        async for chunk in response:
            delta = chunk.choices[0].delta

            # Accumulate text
            if delta.content:
                text_parts.append(delta.content)
                if on_token is not None:
                    on_token(delta.content)

            # Accumulate tool call fragments
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": "",
                        }
                    else:
                        # Update name if provided on a later chunk
                        if tc.function.name is not None:
                            tool_calls_by_index[idx]["name"] = tc.function.name
                        # Update id if provided
                        if tc.id and tc.id != f"call_{idx}":
                            tool_calls_by_index[idx]["id"] = tc.id
                    # Concatenate argument fragments
                    if tc.function.arguments:
                        tool_calls_by_index[idx]["arguments"] += tc.function.arguments

        # If no tool calls, we're done
        if not tool_calls_by_index:
            final_text = "".join(text_parts)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(final_text)
            return final_text

        # Build the assistant message with tool calls (for history)
        assistant_tool_calls = []
        for idx in sorted(tool_calls_by_index.keys()):
            tc_data = tool_calls_by_index[idx]
            assistant_tool_calls.append({
                "id": tc_data["id"],
                "type": "function",
                "function": {
                    "name": tc_data["name"],
                    "arguments": tc_data["arguments"],
                },
            })

        assistant_message = {
            "role": "assistant",
            "content": "".join(text_parts) if text_parts else None,
            "tool_calls": assistant_tool_calls,
        }
        messages.append(assistant_message)

        # Execute each tool and collect results
        for idx in sorted(tool_calls_by_index.keys()):
            tc_data = tool_calls_by_index[idx]
            tool_name = tc_data["name"]
            try:
                tool_args = json.loads(tc_data["arguments"])
            except json.JSONDecodeError:
                tool_args = {}

            if tool_name == "web_search":
                result = web_search(**tool_args)
            elif tool_name == "web_fetch":
                result = await web_fetch(**tool_args)
            else:
                result = f"Unknown tool: {tool_name}"

            messages.append({
                "role": "tool",
                "tool_call_id": tc_data["id"],
                "name": tool_name,
                "content": str(result),
            })

        # Loop back to call litellm again with tool results injected


async def run_pipeline(
    topic: str,
    topic_dir: Path,
    models: dict,
    num_researchers: int = 3,
    on_token: callable = None,
) -> None:
    """Run the full research pipeline for a topic."""

    notes_dir = topic_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    # Initialize log file
    log_path = notes_dir / "log.md"
    log_path.write_text(f"# Research Log\n\nTopic: {topic}\n\n")

    def append_log(entry: str) -> None:
        with log_path.open("a") as f:
            f.write(entry + "\n")

    # Load system prompts
    orchestrator_prompt = _load_agent_prompt("research-orchestrator.md")
    researcher_prompt = _load_agent_prompt("web-researcher.md")
    fact_checker_prompt = _load_agent_prompt("fact-checker.md")
    red_team_prompt = _load_agent_prompt("red-team.md")

    # ── Step 1: Problem definition ──────────────────────────────────────────
    append_log("## Stage: Problem Definition")

    problem_def_path = notes_dir / "problem-definition.md"
    problem_def = await run_agent(
        system_prompt=orchestrator_prompt,
        user_message=(
            f"Define the research problem for the following topic: {topic}\n\n"
            "Establish scope, key questions, and success criteria."
        ),
        model=models["orchestrator"],
        tools=[],
        output_path=problem_def_path,
        on_token=on_token,
        agent_role="orchestrator",
    )

    append_log(f"Problem definition saved to: {problem_def_path}")

    # ── Step 2: Research (parallel) ─────────────────────────────────────────
    append_log("## Stage: Research")

    async def run_researcher(i: int) -> str:
        researcher_path = notes_dir / f"researcher-{i}.md"
        result = await run_agent(
            system_prompt=researcher_prompt,
            user_message=(
                f"Research the following topic: {topic}\n\n"
                f"Sub-question {i + 1} of {num_researchers}: "
                f"Investigate angle {i + 1} of this topic.\n\n"
                f"Problem definition:\n{problem_def}"
            ),
            model=models["web_researcher"],
            tools=["web_search", "web_fetch"],
            output_path=researcher_path,
            on_token=on_token,
            agent_role="web_researcher",
        )
        append_log(f"Researcher {i} complete: {researcher_path}")
        return result

    researcher_results = await asyncio.gather(
        *[run_researcher(i) for i in range(num_researchers)]
    )

    # Collect all researcher notes
    researcher_notes = "\n\n---\n\n".join(
        f"## Researcher {i} Notes\n\n{result}"
        for i, result in enumerate(researcher_results)
    )

    # ── Step 3: Fact check ──────────────────────────────────────────────────
    append_log("## Stage: Fact Check")

    fact_check_path = notes_dir / "fact-check.md"
    fact_check = await run_agent(
        system_prompt=fact_checker_prompt,
        user_message=(
            f"Topic: {topic}\n\n"
            f"Please fact-check the following web_researcher notes:\n\n"
            f"{researcher_notes}"
        ),
        model=models["fact_checker"],
        tools=[],
        output_path=fact_check_path,
        on_token=on_token,
        agent_role="fact_checker",
    )

    append_log(f"Fact check saved to: {fact_check_path}")

    # ── Step 4: Red team ────────────────────────────────────────────────────
    append_log("## Stage: Red Team")

    red_team_path = notes_dir / "red-team.md"
    red_team = await run_agent(
        system_prompt=red_team_prompt,
        user_message=(
            f"Topic: {topic}\n\n"
            f"Please challenge the following research notes and identify weaknesses:\n\n"
            f"## Research Notes\n\n{researcher_notes}\n\n"
            f"## Fact Check\n\n{fact_check}"
        ),
        model=models["red_team"],
        tools=[],
        output_path=red_team_path,
        on_token=on_token,
        agent_role="red_team",
    )

    append_log(f"Red team saved to: {red_team_path}")

    # ── Step 5: Final report ────────────────────────────────────────────────
    append_log("## Stage: Final Report")

    report_path = topic_dir / "report.md"
    await run_agent(
        system_prompt=orchestrator_prompt,
        user_message=(
            f"Write a comprehensive final research report on: {topic}\n\n"
            f"## Problem Definition\n\n{problem_def}\n\n"
            f"## Research Notes\n\n{researcher_notes}\n\n"
            f"## Fact Check\n\n{fact_check}\n\n"
            f"## Red Team Review\n\n{red_team}"
        ),
        model=models["orchestrator"],
        tools=[],
        output_path=report_path,
        on_token=on_token,
        agent_role="orchestrator",
    )

    append_log(f"Final report saved to: {report_path}")
    append_log("## Pipeline Complete")
