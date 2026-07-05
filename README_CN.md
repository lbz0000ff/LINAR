# LINAR

**LINAR Is Not A Retriever.**

LINAR 是一个带有记忆的研究 agent 工作台。它能规划、调研、验证和记忆——把每一次交互视为跨会话持续对话的一部分，而非孤立的问答回合。

基于长期 agent 人格构建，LINAR 将深度研究、工具使用和状态导向记忆集成为一个自主工作流。

> [English](README.md)

---

## 核心能力

- **深度研究** — 多波次并行研究，配合 analyst 和 critic 子 Agent。每一波从多个角度展开，交叉验证结果，并可对关键结论进行对抗式审查，最终合成带引用的报告。
- **长期记忆** — 事实跨会话持久化。系统将已知信息编译为结构化 prompt 视图，检测矛盾，并把新信息合并到按主题组织的记忆状态中。
- **工具型 Agent** — 20+ 内置工具，覆盖网页搜索、文件 I/O、Shell 执行、记忆、计划、工作区管理和视觉能力。研究任务可通过 DAG 计划执行器编排。
- **模块化技能系统** — 技能是带 YAML frontmatter 的 Markdown 文件。无需写 Python 代码即可编写新技能。
- **双界面** — Web UI（Vue 3 + Electron）+ TUI（`prompt_toolkit` + Rich）。
- **插件架构** — 通过 MCP（Model Context Protocol）集成外部工具。

---

## 快速开始

```bash
# 克隆并进入项目
git clone https://github.com/lbz0000ff/linar.git
cd linar
```

使用 `uv` 管理 Python 虚拟环境：

```bash
# 创建虚拟环境
uv venv

# 激活虚拟环境（macOS/Linux）
source .venv/bin/activate
# 或激活虚拟环境（Windows）
.venv\Scripts\activate

# 安装 Python 依赖
uv pip install -r requirements.txt

# 配置 API 密钥
cp agent/config.yaml.example agent/config.yaml
# 编辑 agent/config.yaml —— 设置 LLM provider、model 和搜索后端
# API key 从环境变量读取

# 首次安装 GUI 依赖
cd gui && npm install && cd ..

# 启动 Electron GUI
python linar.py --gui

# 或启动终端界面
python linar.py

# 或构建 Web UI 并启动生产 Web 服务
cd gui && npm run build && cd ..
python linar.py --web
# 然后打开 http://127.0.0.1:8080
```

`python linar.py --gui` 会同时启动 FastAPI 后端和 Electron/Vite GUI，并在你按 `Ctrl+C` 或 GUI 进程退出时一起停止。

仅开发前端时：

```bash
cd gui
npm run dev
```

---

## Deep Research

运行 `\deep-research {query}` 启动一次深度研究任务。

示例：

```
\deep-research Could you please help me investigate the current situation of the precious metals industry?
```

LINAR 会在 `workspaces/` 目录下创建对应任务的工作区。研究任务完成后，会将 Markdown 报告写入 `workspaces/{task_name}/report.md`。

---

## 配置

复制示例配置并编辑：

```bash
cp agent/config.yaml.example agent/config.yaml
```

在环境变量中设置 API key。完整选项见配置文件。`linar.py` 会做轻量依赖检查，并可在首次运行时从 `requirements.txt` 安装缺失的 Python 依赖。

默认搜索后端是 [Tavily](https://www.tavily.com/)，需要在环境变量中设置 `TAVILY_API_KEY`。你可以在 `agent/config.yaml` 中切换到 DuckDuckGo 或 Serper，也可以通过 MCP 添加搜索服务。

---

### 环境要求

- Python 3.10+
- Node.js 18+（Web UI 需要）
- 至少一个 LLM 提供商的 API 密钥

---

## 架构

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

关键组件：

- **`agent/orchestrator/`** — 基于 FSM 的执行流程、技能生命周期、记忆提取，以及围绕 agent 主循环的编排胶水层
- **`agent/memory/`** — 状态导向记忆系统：Fact 存储、Topic 注册、View 编译器、Collision 检测器
- **`agent/tool/`** — 按领域组织的工具实现（`basic_tools`、`mcp_tools`）
- **`agent_types/`** — 预定义子 Agent 配置（`web_researcher`、`analyst`、`critic`），使用 YAML frontmatter
- **`skills/`** — 运行时动态加载的 Markdown 技能
- **`gui/`** — Vue 3 前端与 Electron 外壳

---

## 技术栈

| 层 | 技术 |
|-------|-----------|
| Agent 核心 | Python 3.10+, asyncio |
| LLM API | OpenAI 兼容 provider（DeepSeek、Zhipu、StepFun、Ollama/LM Studio 等） |
| Web UI | Vue 3, Vite, Electron |
| TUI | prompt_toolkit, Rich |
| 持久化 | SQLite |
| 外部工具 | MCP (Model Context Protocol) |

---

## 项目状态

LINAR 正在积极开发中。核心研究和记忆系统已可运行；API 和内部接口可能仍有变化。

评测成绩：
- [**DeepResearch Bench**](https://github.com/Ayanami0730/deep_research_bench)：48.56

---

## 许可证

MIT — 参见 [LICENSE](LICENSE)。
