# LINAR

**LINAR Is Not A Retriever.**

LINAR is an Agent Runtime and deep-research prototype for long-running tasks. It combines tool use, a finite-state machine, DAG execution, session memory, and evaluation in one runtime, modeling a task as an input-state-plan-execute-feedback loop rather than a single chat turn.

The project explores controllable and observable agent execution and remains under active development.

> [中文](README_CN.md)

---

## Key Capabilities

- **Agent Runtime** - An OpenAI-compatible ReAct tool loop is governed by an FSM. The blocking `create_plan` tool executes a DAG internally and returns structured results to the main agent.
- **Deep Research** - `web_researcher`, `analyst`, and `critic` sub-agents divide retrieval, analysis, and optional review work before producing a Markdown report with source links.
- **State-Oriented Memory** - Cross-session facts are organized as Facts, Topics, and compiled Views with deduplication and conflict checks. This is an experimental personal-state mechanism, not a general-purpose knowledge base.
- **Observable Execution** - The GUI shows DAG nodes, sub-agent tool events, duration, token usage, and cache-hit metrics for diagnosing long-running tasks.
- **Context and Budget Controls** - History compaction, tool-result truncation, sub-agent LLM-call limits, and research-specific search/fetch budgets bound common sources of context growth.
- **Skills and MCP** - Markdown Skills load on demand at runtime. Enabled MCP servers initialize in parallel, and their tools join the same registry.
- **Three Run Modes** - TUI, Electron GUI, and a Web mode serving the built frontend.

---

## Prerequisites

- Python 3.10+
- Node.js 18+ with [npm](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm) for the Web UI
- [uv](https://docs.astral.sh/uv/) is recommended for Python environment management; the launcher falls back to `pip`
- API key for at least one LLM provider

---

## Quick Start

```bash
# Clone & enter
git clone https://github.com/lbz0000ff/linar.git
cd linar
```

Use [uv](https://docs.astral.sh/uv/) to manage the Python virtual environment:
```bash
# Create a virtual environment
uv venv

# Activate it (macOS/Linux)
source .venv/bin/activate
# Or activate it (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Install Python dependencies
uv pip install -r requirements.txt

# Configure environment variables and runtime settings
cp .env.example .env
cp agent/config.yaml.example agent/config.yaml
# Put API keys in .env
# Set providers, models, tool permissions, and search backends in agent/config.yaml

# Install GUI dependencies once with npm
cd gui && npm install && cd ..

# Start the Electron GUI
python linar.py --gui

# Or start the TUI
python linar.py

# Or build the Web UI and start the production web server
cd gui && npm run build && cd ..
python linar.py --web
# Then open http://127.0.0.1:8080
```

`python linar.py --gui` starts both the FastAPI backend and the Electron/Vite GUI, and stops both when you press `Ctrl+C` or close the GUI process. The launcher prefers `uv` for missing dependencies and falls back to the current Python interpreter's `pip`.

On Windows PowerShell, use `Copy-Item` instead of `cp` in the commands above.

For frontend-only development:

```bash
cd gui
npm run dev
```

---

## Deep Research

Run `\deep-research {query}` to start a deep research task.

Example:

```
\deep-research Could you please help me investigate the current situation of the precious metals industry?
```

LINAR creates a task workspace under `workspaces/`. Once the research task is done, it writes a Markdown report to `workspaces/{task_name}/report.md`.

Deep Research executes as follows:

1. The main agent creates one DAG wave for the research question.
2. Ready tasks run in parallel, and sub-agents return structured findings and sources through `submit_output`.
3. After each wave, the Deep Research Skill directs the main agent to call a state reader for a compact overview and selected evidence IDs.
4. Based on coverage, the main agent decides whether to continue retrieval and analysis or run critic review before writing the report.

Sub-agent LLM-call limits and `web_researcher` search/fetch budgets are configurable in `agent/config.yaml`. Critic review and source-priority guidance in the Skill improve traceability and review pressure; they do not guarantee that a report is correct.

---

## Configuration

Copy the environment and configuration examples:

```bash
cp .env.example .env
cp agent/config.yaml.example agent/config.yaml
```

Keep API keys in `.env` or system environment variables; do not put or commit them in `agent/config.yaml`. The configuration covers:

- main and auxiliary model providers/models
- toolsets and `safe` / `auto` / `review` permission modes
- chat-history compaction and per-tool output limits
- sub-agent LLM-call limits and research search/fetch budgets
- Crawl4AI preview size, browser channel, and `robots.txt` policy
- MCP servers, logging, and memory settings

The default search backend is [Tavily](https://www.tavily.com/), which requires `TAVILY_API_KEY`. You can switch to DuckDuckGo or Serper or add MCP search servers. Web fetching uses Crawl4AI: full Markdown is saved in the active workspace while only a bounded preview is returned to the model.

---

## Architecture

```
                   ┌──────────────────────────┐
                   │     Web UI / TUI         │
                   └──────────┬───────────────┘
                              │ WebSocket
                   ┌──────────▼───────────────┐
                   │       Orchestrator       │
                   │  (FSM: IDLE → INGEST →   │
                   │   PROCESS → COMPLETE)     │
                   └──────┬──────────┬────────┘
                          │          │
              ┌───────────▼──┐  ┌────▼──────────┐
              │   Skill      │  │  DAG Plan     │
              │   Manager    │  │  Executor     │
              └───────────┬──┘  └────┬──────────┘
                          │          │
              ┌───────────▼──────────▼──────────┐
              │       Blocking create_plan      │
              │  DAG scheduling + sub-agents +  │
              │      structured submission      │
              └───────────┬─────────────────────┘
                          │
              ┌───────────▼─────────────────────┐
              │    20+ Built-in Tools + MCP     │
              │  (web, file, shell, memory,      │
              │   vision, plan, etc.)            │
              └─────────────────────────────────┘
```

Key components:

- **`agent/orchestrator/`** - FSM-based execution flow, skill lifecycle, memory extraction, and orchestration glue around the agent loop
- **`agent/memory/`** - State-oriented memory system: Fact store, Topic registry, View compiler, Collision detector
- **`agent/tool/basic_tools/tool_plan.py`** - Blocking `create_plan`, DAG sub-agent scheduling, budgets, and structured submission
- **`agent/tool/`** - Built-in and MCP tool implementations organized by domain
- **`agent_types/`** - Predefined sub-agent profiles (`web_researcher`, `analyst`, `critic`) with YAML frontmatter
- **`skills/`** - Markdown-defined skills loaded dynamically at runtime (`deep-research`, `code-doc`, `skill-writer`, `system-guide`, etc.)
- **`gui/`** - Vue 3 frontend + Electron shell

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent Core | Python 3.10+, asyncio |
| LLM API | OpenAI-compatible providers (DeepSeek, Zhipu, StepFun, Ollama/LM Studio, etc.) |
| Web UI | Vue 3, Vite, Electron |
| TUI | prompt_toolkit, Rich |
| Persistence | SQLite |
| External Tools | MCP (Model Context Protocol) |

---

## Project Status

LINAR is an experimental personal project under active development. The agent tool loop, FSM, DAG execution, Deep Research, memory, and basic evaluation pipeline are implemented, while APIs, internal interfaces, and research strategies may still change.

Interim evaluation:

- [**DeepResearch Bench**](https://github.com/Ayanami0730/deep_research_bench) RACE (2026-07-16, 29 valid tasks): **Overall 52.42**
  - Comprehensiveness: 52.31
  - Insight: 52.02
  - Instruction Following: 53.71
  - Readability: 51.02

Language distribution across the 29 tasks:

| Language | Count |
|----------|------:|
| Chinese | 29 |
| English | 0 |

Using the DeepResearch Bench dataset's original `topic` fields:

| Category | Count |
|----------|------:|
| Science & Technology | 8 |
| Finance & Business | 6 |
| Software Development | 5 |
| Education & Jobs | 4 |
| Health | 3 |
| Literature | 2 |
| History | 1 |

The prompts span scientific research, software engineering, industry and finance, local public finance and policy, education and employment, health, and the humanities. Policy is a cross-cutting theme rather than a standalone dataset `topic`.

This is an interim result from 29 valid Chinese-language tasks. It contains no English tasks and is not a complete 100-task leaderboard result, so it does not by itself establish English research performance or a fixed score across models, configurations, and code revisions. The repository's evaluation harness supports isolated tasks, resume checkpoints, failure ledgers, and retries; answer generation and later scoring are separate steps.

Current boundaries:

- tool permissions are application-level policy, not an operating-system sandbox;
- critic review, source-priority guidance in the Skill, and citation retention improve reviewability but do not guarantee factual correctness;
- MCP servers, model providers, and web services still depend on local configuration and external availability.

---

## License

MIT — see [LICENSE](LICENSE).
