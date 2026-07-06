---
name: system-guide
description: Help LINAR understand, configure, extend, and troubleshoot itself
allowed-tools: 
  - read_file 
  - search_files
---

# LINAR System Guide

Use this skill when the user asks how LINAR works, how to configure it, how to
extend it with skills or MCP servers, where a behavior comes from, or how to
troubleshoot runtime issues.

LINAR is an autonomous task execution system, not only a prompt wrapper. It
combines an LLM conversation loop, tool calling, a state-machine-oriented
orchestrator, Markdown skills, MCP tools, DAG planning, subagents, hooks, and
state-oriented memory.

## Operating Principles

- Prefer current source code over memory or old docs. This project changes quickly.
- Inspect the relevant code path before giving detailed implementation advice.
- When a user asks "how do I do X?", answer with the practical workflow first,
  then mention the internal files only when useful.
- When a user asks LINAR to install or configure something, treat that as an
  operational task: read the instructions, infer the required config, apply the
  smallest safe change, and verify.
- Never write API keys, tokens, passwords, or private credentials into tracked
  files or examples. Use environment variables such as `${TAVILY_API_KEY}`.
- Do not edit `agent/config.yaml` for a purely explanatory question. Edit it
  only when the user is clearly asking LINAR to configure the local runtime.

## Mental Model

At a high level:

```text
user request
  -> prompt + skill listing + memory/context
  -> LLM response
  -> tool calls
  -> tool results appended to history
  -> repeat until final response, interruption, or turn limit
```

For multi-step work, LINAR can create a DAG plan and run subagents in parallel.
For specialized behavior, LINAR loads a skill. For external capabilities, LINAR
can load MCP tools from configured or locally discovered MCP servers.

The intended state flow is:

```text
IDLE -> INGEST -> PROCESS -> COMPLETE -> IDLE
                  |
                  v
            SKILL_LOAD -> SKILL_EXEC -> SKILL_UNLOAD -> COMPLETE -> IDLE
```

## Configuration

LINAR reads local configuration from `agent/config.yaml`, creating it from
`agent/config.yaml.example` when missing. Treat `agent/config.yaml` as a local
runtime file that may contain machine-specific paths and secrets.

Use these rules:

- Put shareable defaults and commented examples in `agent/config.yaml.example`.
- Put local runtime choices in `agent/config.yaml`.
- Put secrets in environment variables and reference them as `${ENV_VAR}`.
- Do not commit `agent/config.yaml`.

Common configuration areas:

- model providers and model names
- enabled toolsets
- web search backend
- vision provider
- permission modes
- MCP server definitions
- memory settings
- prompt file order

## Skills

Skills are Markdown-defined behaviors under `skills/<name>/SKILL.md`.

Important behavior:

- Skills are discovered from `skills/*/SKILL.md`.
- LINAR dynamically tells the model which skills are available.
- The model invokes the generic `skill` tool by name.
- Loading a skill appends the skill instructions to LINAR's base prompt, so the
  identity, memory, and project rules remain available.
- `allowed-tools` narrows the visible tool set for that skill.
- Optional `skill.json` and `scripts/` can expose bundled helper scripts as
  skill-specific tools.

### Installing Or Updating Skills

When the user asks to install or create a skill:

1. Read the source material or installation instructions.
2. Create or update `skills/<skill-name>/SKILL.md`.
3. Add optional `skill.json` or `scripts/` only when the skill needs executable
   helpers.
4. Keep frontmatter concise: `name`, `description`, and `allowed-tools` are the
   most important fields.
5. Verify the skill loader can parse the skill.
6. Tell the user whether LINAR needs a restart for the new skill to appear.

Use `skill-writer` for detailed guidance on authoring skills.

## MCP Servers

MCP servers add external tools to LINAR. LINAR supports two MCP discovery paths:

- `mcp_servers:` entries in `agent/config.yaml`
- local auto-discovery under `agent/tool/mcp_tools/server/<name>/`

Configured MCP tools are exposed to the model as names like:

```text
mcp_<server_name>_<tool_name>
```

MCP startup is intentionally non-blocking in GUI/Web mode: native tools load
first, MCP servers start in the background, then their tools are merged into
active sessions. Command `/reload_mcp` restarts MCP servers and refreshes
the agent's tool list.

### Installing MCP Servers

When the user asks LINAR to install an MCP server, use this workflow:

1. Read the installation instructions from the provided file, URL, README, or
   package documentation.
2. Extract the required `command`, `args`, environment variables, package
   manager, and authentication requirements.
3. Install required packages only when the user requested installation or has
   clearly approved it.
4. Prefer a local auto-discovered server directory when bundling a project-local
   MCP server makes sense.
5. Otherwise configure `mcp_servers:` in `agent/config.yaml`.
6. Before editing `agent/config.yaml`, create a timestamped backup next to it.
7. Never write secret values directly. Use `${ENV_VAR}` placeholders and tell
   the user which environment variables to set.
8. Reload MCP tools with `/reload_mcp` in TUI, or restart GUI/Web if needed.
9. Verify the new tools appear with the `mcp_<server>_...` prefix or report the
   startup error clearly.

If LINAR is only being asked "how would I install this?", provide the YAML
snippet and commands without changing local config.

### MCP Config Shape

Use this shape for stdio MCP servers:

```yaml
mcp_servers:
  example:
    enabled: true
    command: npx
    args: ["-y", "@example/mcp-server"]
    env:
      EXAMPLE_API_KEY: "${EXAMPLE_API_KEY}"
```

Prefer direct installed commands over `npx -y` or `uvx` when startup speed
matters, but only after verifying the binary is available on PATH.

## Tool System

Built-in tools are grouped into toolsets such as file, shell, web, memory,
interactive, plan, vision, and MCP. MCP tools are merged into the same tool
dictionary as native tools.

When explaining tool availability:

- Check enabled toolsets in config.
- Check whether MCP has finished loading.
- Check whether a skill's `allowed-tools` has filtered the active tool set.
- Check whether vision tools require model/provider configuration.

## Deep Research

Deep Research is a skill plus DAG/subagent workflow.

Key ideas:

- The Deep Research skill defines the overall procedure.
- DAG execution runs specialized subagent profiles.
- Subagents submit structured output through `submit_output`.
- Shared research state is accumulated in `research_state.json`.
- Reports are written into a task workspace.

When improving Deep Research, prefer architecture-level fixes when needed:
subagent profiles, structured output schema, plan execution, asset handling,
and report generation rules are all valid places to improve behavior.

## Troubleshooting Playbook

When something does not work:

1. Identify whether the problem is config, tool availability, model output,
   permission handling, state-machine flow, or external dependency failure.
2. Read the relevant current code path.
3. Reproduce with the smallest command or interaction possible.
4. Check logs and emitted events.
5. Make the smallest fix that addresses the root cause.
6. Verify with a focused test or runtime check.

Common examples:

- Skill does not appear: reload/restart and verify the skill loader can parse
  `skills/<name>/SKILL.md`.
- MCP tool does not appear: check `mcp_servers`, command availability, startup
  timeout, stderr logs, and `/reload_mcp`.
- Vision tool missing: check `vision.enabled`, model/provider settings, and
  whether the active skill allows the tool.
- Agent stops early: check `max_turns` and whether the last message reports an
  LLM call limit.
- Config changes do not apply: restart GUI/Web or reload the relevant runtime
  subsystem when available.

## Answer Style

Start with the direct answer, then give the workflow. Include file paths only
when they help the user act. If you inspected code, name the important files and
what you learned from them. If behavior may be stale or environment-specific,
say so plainly.
