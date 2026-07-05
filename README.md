# LINAR

**LINAR Is Not A Retriever.**

LINAR is a research agent workspace with memory. It plans, investigates, verifies, and remembers - treating every interaction as part of an ongoing conversation that spans sessions, not isolated Q&A turns.

Built around a long-term agent persona, LINAR integrates deep research, tool use, and state-oriented memory into a single autonomous workflow.

> [中文](README_CN.md)

---

## Key Capabilities

- **Deep Research** - Multi-wave parallel research with analyst and critic sub-agents. Each wave fans out across angles, cross-validates results, and can adversarially review claims before synthesizing a cited report.
- **Long-Term Memory** - Facts persist across sessions. The system compiles what it knows into structured prompt views, detects contradictions, and merges new information into a topic-organized memory state.
- **Tool-Using Agent** - 20+ built-in tools for web search, file I/O, shell execution, memory, planning, workspace management, and vision. Research tasks can be orchestrated through a DAG-based plan executor.
- **Modular Skill System** - Skills are Markdown files with YAML frontmatter. Anyone can write a skill without touching Python code.
- **Dual Interface** - Web UI (Vue 3 + Electron) and TUI (`prompt_toolkit` + Rich).
- **Plugin Architecture** - MCP (Model Context Protocol) servers for external tool integration.

---

## Prerequisites

- Python 3.10+
- Node.js 18+ with [npm](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm) for the Web UI
- [uv](https://docs.astral.sh/uv/) for Python environment management
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
# Or activate it (Windows)
.venv\Scripts\activate

# Install Python dependencies
uv pip install -r requirements.txt

# Configure API keys
cp agent/config.yaml.example agent/config.yaml
# Edit agent/config.yaml - set LLM providers, models, and search backends.
# API keys are read from environment variables.

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

`python linar.py --gui` starts both the FastAPI backend and the Electron/Vite GUI, and stops both when you press `Ctrl+C` or close the GUI process.

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

---

## Configuration

Copy the example config and edit:

```bash
cp agent/config.yaml.example agent/config.yaml
```

Set API keys in your environment. See the config file for all options. `linar.py` also performs a lightweight dependency check and can install missing Python dependencies from `requirements.txt` on first run.

The default search backend is [Tavily](https://www.tavily.com/), which requires `TAVILY_API_KEY` in your environment. You can switch to DuckDuckGo or Serper, or add MCP search servers, in `agent/config.yaml`.

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
              │         Sub-Agent Pool          │
              │  (web_researcher / analyst /    │
              │   critic - parallel execution)   │
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
- **`agent/tool/`** - Tool implementations organized by domain (`basic_tools`, `mcp_tools`)
- **`agent_types/`** - Predefined sub-agent profiles (`web_researcher`, `analyst`, `critic`) with YAML frontmatter
- **`skills/`** - Markdown-defined skills loaded dynamically at runtime
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

LINAR is in active development. The core research and memory systems are functional; APIs and internal interfaces may still change.

Benchmark scores:
- [**DeepResearch Bench**](https://github.com/Ayanami0730/deep_research_bench): 48.56

---

## License

MIT — see [LICENSE](LICENSE).
