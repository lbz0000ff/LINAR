# Lily — AI Agent Framework

An extensible AI agent framework with persistent memory, tool-calling, skill plugins, task planning, and a streaming REPL terminal.

## Quick Start

```bash
# Set API key
set DEEPSEEK_API_KEY=your_key_here

# Start the terminal
cd agent && python cli/terminal.py
```

## Features

- **LLM-driven agent loop** — streaming response, multi-turn tool calling, permission-aware execution
- **Persistent memory** — 4-tier memory (user traits, conversation facts, archived content, event bookmarks) with automatic LLM-based compression
- **Tool system** — file operations, shell commands, web fetching, date/time, with security checks (path traversal, SSRF, blocked commands)
- **Skill plugins** — markdown-defined skills that swap prompt + tool set at runtime
- **Task planning** — automatic task decomposition for multi-step goals, tracked via plan tools
- **REPL terminal** — rich streaming CLI with configurable themes, reasoning/tool-call display modes, session management
- **Session management** — full conversation history in SQLite, session switching, search
- **Orchestrator** — explicit state machine (IDLE → INGEST → ROUTE → PLAN → PROCESS → COMPLETE) for predictable flow control
- **Permission system** — per-tool allow/ask/deny with runtime overrides and glob pattern support

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
