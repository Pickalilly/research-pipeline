# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This repository contains a research pipeline web application. The goal is a deployable Docker app where users enter a topic, select AI models per agent role, and receive a written research report.

## Architecture

**Stack:** Python, NiceGUI (web UI), LiteLLM (multi-provider AI), Tavily (web search), Docker

**Key files:**
- `app.py` — NiceGUI web UI (topic input, model dropdowns, live log, download button)
- `pipeline.py` — orchestrates the agent pipeline using `asyncio`
- `tools.py` — web search (Tavily) and web fetch implementations
- `config.toml` — default model selections
- `.claude/agents/*.md` — agent system prompts (do not modify these)

**Environment variables** (set in `.env`, never baked into image):
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `TAVILY_API_KEY`

## Research Pipeline

The pipeline runs these steps in sequence:

```
1. Problem definition   (orchestrator agent)
2. Research             (3–5 web-researcher agents in parallel via asyncio.gather)
3. Fact check           (fact-checker agent)
4. Red team             (red-team agent)
5. Final report         (orchestrator agent)
```

Output is written to `topics/[slug]/notes/` inside the container. The UI streams tokens live and shows a download button for `report.md` on completion.

### Agent Roles

| Agent | Model tier | Role |
|---|---|---|
| `web-researcher` | Fast/cheap (e.g. Haiku, gpt-4o-mini) | Researches a single sub-question, saves notes with citations |
| `fact-checker` | Fast/cheap | Verifies claims in research notes against cited sources |
| `red-team` | Capable (e.g. Sonnet, gpt-4o) | Challenges findings, surfaces counterevidence and missing perspectives |
| `orchestrator` | Capable | Defines problem, decomposes into sub-questions, writes final report |

### Output Structure

```
topics/
  [topic-slug]/
    notes/
      log.md
      problem-definition.md
      [subtopic].md
      fact-check.md
      red-team.md
    report.md
```

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python3 app.py

# Build and run with Docker
docker compose up --build
```

The app is accessible at `http://localhost:8080`.

## Multi-Provider Models

LiteLLM routes to the correct provider based on model name prefix:
- `claude-*` → Anthropic
- `gpt-*` or `o*` → OpenAI

Both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` can coexist. Keys for unused providers can be left blank.
