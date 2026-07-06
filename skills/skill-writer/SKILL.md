---
name: skill-writer
description: Guide LINAR in creating or improving SKILL.md files in the skills/ directory
---

## When to use

Trigger when the user asks you to:
- Create a new skill or write a SKILL.md file
- Convert a downloaded skill (e.g. from OpenClaw forum)
- Improve or fix an existing skill
- Explain how skills work
- Help LINAR extend its own skill set

## Skill directory structure

```
skills/<skill-name>/
├── SKILL.md            # Required: instructions + frontmatter
├── skill.json          # Optional: OpenClaw metadata (skillFile, configSchema)
└── scripts/
    └── helper.py       # Optional: bundled Python/shell scripts
```

Bundled Python scripts are automatically registered as `<skill_name>_<script_name>` tools. The script should expose an `execute(command, args)` function or `handle_<command>(args)` handlers.

## Current LINAR skill behavior

- Skills are discovered from `skills/*/SKILL.md`.
- Available skills are dynamically announced in `_build_llm_messages()` as a system-reminder.
- The model invokes the generic `skill` tool with the skill name; do not rely on the deprecated `skill_view` flow.
- Loading a skill appends its instructions to the base prompt, preserving LINAR's identity, memory, and safety constraints.
- `allowed-tools` filters the visible tool set for the active skill. Omit it when the skill should inherit all tools.

## Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Kebab-case name, used as `/name` |
| `description` | Yes | One line shown in /help. Must let the agent decide when to use. |
| `allowed-tools` | No | Space-separated or YAML list of tool names. Omit = inherit all. |
| `model` | No | Model override for this skill (e.g. `claude-sonnet-4-20250514`) |
| `effort` | No | `low`, `medium`, `high`, `xhigh`, `max` |
| `context` | No | `fork` to run in isolated subagent (prevents history pollution) |
| `agent` | No | Subagent type when `context: fork` (`Explore`, `Plan`, `general-purpose`) |
| `shell` | No | `bash` (default) or `powershell` |
| `user-invocable` | No | `false` = hide from `/` menu |
| `disable-model-invocation` | No | `true` = only manual `/name` invocation |

## Available tools

| Tool | Purpose |
|------|---------|
| `read_file` | Read file contents |
| `search_files` | Search by glob/regex |
| `write_file` | Write file (overwrites!) |
| `patch_file` | Precise edit (safer) |
| `cmd_execute` | Run shell commands |
| `web_fetch` | HTTP GET (text only) |
| `web_search` | Search the web |
| `ask_user` | Ask the user |
| `skill` | Load another skill by name |
| `create_plan` | Create and execute a DAG plan |
| `workspace` | Create or switch task workspaces |

## How to write a good system prompt

The skill prompt is appended to LINAR's base prompt, but it still must be self-contained enough to guide the task without assuming hidden context.

Include these sections in order:

### 1. Trigger conditions

Tell the agent exactly when to use this skill.

```markdown
## When to use

Trigger when the user asks to:
- ...
```

### 2. Step-by-step procedure

Concrete, ordered steps.

```markdown
## Procedure

1. First, ...
2. Then, ...
```

### 3. Rules and constraints

Boundaries, prohibitions, hard requirements.

### 4. Output format (if applicable)

Provide a template for structured output.

## Converting skills from other formats

When converting a skill from OpenClaw forum or other sources:

1. **Read all files** in the skill directory (SKILL.md, skill.json, *.py)
2. **Check for skill.json** — if it has `skillFile: "xxx.py"`, the Python script will be auto-registered as a tool. Set `allowed-tools` to include `<name>_script` so the LLM can call it.
3. **Keep the Python script** in place — `skill.py` now auto-loads it
4. **Rewrite SKILL.md** with proper frontmatter + system prompt that tells the LLM:
   - When to call the script tool vs using built-in tools
   - What commands/functions the script exposes
   - Expected input/output format

### Example: converting a ComfyUI skill

Original has:
- `comfyui.py` — Python module with `execute(command, args)` entry point
- `skill.json` — points `skillFile` to `comfyui.py`

The converted SKILL.md should:
- Set `context: fork` to isolate execution
- Set `allowed-tools: <name>_script cmd_execute web_fetch`
- Tell the LLM to use the `<name>_script` tool with commands like `generate`, `set_url`, `status`

## Common mistakes

- **No trigger conditions** — agent can't decide when to use it
- **Vague steps** — be concrete
- **Overly broad allowed-tools** — grant only what's needed
- **Assuming outside context** — skill instructions are appended to the base prompt, but should still be clear and self-contained
- **Ignoring bundled scripts** — if `skill.json` has `skillFile`, the script is auto-loaded as a tool
