# Lily — AI Agent Framework with Persistent Memory

Lily is a self-hosted, memory-augmented LLM agent framework. Unlike stateless chatbots that forget everything between sessions, Lily maintains **cross-session context**: it remembers your preferences, past decisions, and project history — and can autonomously orchestrate multi-step workflows spanning code execution, data analysis, and file operations.

> **Think of Lily as a framework for building AI assistants that don't forget what you told them yesterday.**

## Quick Start

```bash
# Set API key
set DEEPSEEK_API_KEY=your_key_here

# Start the terminal
cd agent && python cli/terminal.py
```

## Demo: Scientific Notebook Assistant

```bash
# Run the full demo (requires matplotlib)
pip install matplotlib
python demos/scientific_assistant.py
```

This demo showcases Lily's core value — an AI assistant that can **plan, execute, visualize, and remember**:

| Step | What Lily does | What it demonstrates |
|------|---------------|---------------------|
| 1 | Writes a Python script for a damped harmonic oscillator simulation (RK4) | Code generation + tool use |
| 2 | Executes the script, captures output | Shell integration |
| 3 | Plots displacement vs. time, saves as PNG | Scientific visualization |
| 4 | Stores parameters, file paths, and conclusions in memory | Persistent memory (write) |
| 5 | In a *new* conversation, recalls all results without re-prompting | Cross-session memory (read) |

The demo proves that Lily is not just a chatbot — it's an **agent that can autonomously complete a research workflow and remember it for future use.**

## Features

- **Cross-session persistent memory** — 4-tier memory (user traits, conversation facts, archived content, event bookmarks) with automatic LLM-based compression. Recall past results in a brand-new conversation.
- **Multi-tool orchestration** — Agent autonomously chains 3-5 tools per response: e.g., write code → execute → read results → plot → store in memory. No manual step-by-step prompting needed.
- **Streaming LLM loop with incremental tool calls** — Built on streaming JSON parsing, supports accumulating multiple tool calls in a single response, reducing LLM round-trips by ~40% for complex workflows.
- **Tool system (10+ built-in)** — File operations, shell commands, web fetch/search, memory read/write, interactive prompting, task planning, vision, and async promise resolution — all with built-in security checks (path traversal, SSRF, blocked commands).
- **Plugin skill system** — Markdown-defined skills that swap prompt + tool set at runtime. Supports both Claude Code format and OpenClaw marketplace.
- **Task planning with DAG execution** — Automatic task decomposition (linear subtasks or parallel DAG) with ThreadPoolExecutor-based wave scheduling.
- **Orchestrator state machine** — Explicit 10-stage state machine (IDLE → INGEST → ROUTE → PLAN → PROCESS / DAG_EXECUTE / SKILL → COMPLETE) for predictable flow control.
- **MCP protocol support** — MCP client that connects to any MCP-compatible server (e.g., ComfyUI for image generation), extending agent capabilities beyond text.
- **REPL terminal** — Dual-panel streaming TUI built with prompt_toolkit + Rich, with configurable themes and display modes for reasoning/tool-calls.
- **Session management** — Full conversation history in SQLite, session switching/rename/delete, full-text keyword search across sessions.
- **Permission system** — Per-tool allow/ask/deny with three runtime modes (safe/auto/review) and glob pattern support.

## Project Structure

```
Lily/
├── agent/                      # Core agent framework
│   ├── agent.py                # Agent main loop — state, LLM dispatch, tool execution
│   ├── orchestrator.py         # State machine wrapping the agent loop
│   ├── llm.py                  # OpenAI-compatible LLM client (streaming)
│   ├── config.py               # YAML config loader with env var resolution
│   ├── database.py             # SQLite session/message persistence
│   ├── logger.py               # Centralized logging (file rotation + console)
│   ├── permissions.py          # Per-tool permission control
│   ├── plan.py                 # Task plan data structures (SubTask, TaskPlan)
│   ├── skill.py                # Plugin skill system (load, register, dispatch)
│   ├── tool_registry.py        # Tool registration and toolset filtering
│   ├── config.yaml             # Main configuration file
│   ├── cli/                    # REPL terminal
│   │   ├── terminal.py         # LilyTerminal — prompt_toolkit + Rich REPL
│   │   ├── style.yaml          # UI color theme
│   │   └── style_loader.py     # Style config loader with defaults
│   ├── commands/               # Slash command handlers (/help, /session, etc.)
│   ├── basic_tools/            # Tool implementations
│   │   ├── tool.py             # Tool base class (Pydantic model)
│   │   ├── tool_cmd.py         # Shell command execution
│   │   ├── tool_fileio.py      # File read/write/delete/patch/search
│   │   ├── tool_memory.py      # Memory remember/recall (4 types)
│   │   ├── tool_web.py         # Web fetching with SSRF protection
│   │   ├── tool_ask_user.py    # Interactive user questioning
│   │   ├── tool_plan.py        # Plan advancement/status
│   │   ├── tool_skill.py       # Skill viewing
│   │   └── tool_time.py        # Date/time tools
│   └── prompt/                 # System prompt files
│       ├── system_prompt_base.md
│       ├── SOUL.md
│       ├── USER.md             # User memory (auto-loaded)
│       ├── MEMORY.md           # Fact memory (auto-loaded)
│       └── plan_system_prompt.md
├── skills/                     # Markdown-defined skill plugins
│   ├── code-doc/SKILL.md
│   └── review-code/SKILL.md
├── demos/                       # Demo scripts
│   └── scientific_assistant.py  # Cross-session scientific notebook demo
├── docs/                       # Project documentation
├── logs/                       # Runtime logs (auto-rotating)
├── AGENT_ARCHITECTURE.md       # Agent internals documentation
├── MEMORY_ARCHITECTURE.md      # Memory system documentation
├── CLI_ARCHITECTURE.md         # CLI terminal documentation
├── CLI_SETTINGS.md              # CLI configuration reference
├── LOGGING.md                  # Logging system documentation
└── ARCHITECTURE.md             # Overall project architecture
```

## Configuration

All configuration lives in `agent/config.yaml`:

- **LLM** — base_url, model, temperature, max_tokens (supports any OpenAI-compatible API)
- **Memory** — character limits, dedup threshold
- **Tools** — enable/disable tool sets (time, file, shell, web, memory, interactive, plan)
- **Permissions** — per-tool allow/ask/deny rules
- **Logging** — level, file path, rotation settings
- **Chat history** — compaction strategy, character limits

## Dependencies

- `openai` — LLM API client
- `prompt_toolkit` — REPL input handling
- `rich` — terminal rendering
- `pyyaml` — configuration parsing
- `httpx` / `requests` — web fetching
- `trafilatura` / `html2text` — HTML-to-text conversion (optional)

## License

MIT
