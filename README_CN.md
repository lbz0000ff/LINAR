# LINAR

**LINAR Is Not A Retriever.**

LINAR 是一个面向长任务的 Agent Runtime 与深度研究原型。它将工具调用、状态机、DAG 任务执行、会话记忆和评测组织在同一套运行时中，把一次任务建模为“输入 → 状态 → 规划 → 执行 → 反馈”的闭环，而不只是单轮问答。

项目主要用于探索可控、可观察的 Agent 执行机制；当前仍在积极开发中。

> [English](README.md)

---

## 核心能力

- **Agent Runtime** — OpenAI 兼容的 ReAct 工具循环由 FSM 管理执行阶段；`create_plan` 在工具内部阻塞执行 DAG，并把结构化结果交还主 Agent。
- **深度研究** — 使用 `web_researcher`、`analyst` 和 `critic` 子 Agent 分工完成检索、分析与可选审查，最终生成带来源链接的 Markdown 报告。
- **状态导向记忆** — 将跨会话事实组织为 Fact、Topic 和可编译 View，并提供去重与冲突检测。它是实验性的个人状态管理机制，不是通用知识库。
- **可观察执行** — GUI 展示 DAG 节点、子 Agent 工具事件、耗时、Token 用量和缓存命中率，便于定位长任务中的失败与成本。
- **上下文与预算控制** — 支持历史压缩、工具结果截断、子 Agent LLM 调用上限，以及研究场景下的搜索/抓取次数限制。
- **Skill 与 MCP** — Markdown Skill 在运行时按需加载；已启用的 MCP server 并行初始化，其工具通过统一注册表接入。
- **三种运行方式** — TUI、Electron GUI，以及服务构建产物的 Web 模式。

---

## 环境要求

- Python 3.10+
- Node.js 18+，Web UI 需要 [npm](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm)
- 推荐使用 [uv](https://docs.astral.sh/uv/) 管理 Python 环境；未安装时启动器会回退到 `pip`
- 至少一个 LLM 提供商的 API 密钥

---

## 快速开始

```bash
# 克隆并进入项目
git clone https://github.com/lbz0000ff/linar.git
cd linar
```

使用 [uv](https://docs.astral.sh/uv/) 管理 Python 虚拟环境：

```bash
# 创建虚拟环境
uv venv

# 激活虚拟环境（macOS/Linux）
source .venv/bin/activate
# 或激活虚拟环境（Windows PowerShell）
.venv\Scripts\Activate.ps1

# 安装 Python 依赖
uv pip install -r requirements.txt

# 配置环境变量和运行参数
cp .env.example .env
cp agent/config.yaml.example agent/config.yaml
# 在 .env 中填写 API key
# 在 agent/config.yaml 中设置 provider、model、工具权限和搜索后端

# 使用 npm 首次安装 GUI 依赖
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

`python linar.py --gui` 会同时启动 FastAPI 后端和 Electron/Vite GUI，并在你按 `Ctrl+C` 或 GUI 进程退出时一起停止。启动器优先使用 `uv` 安装缺失依赖，没有 `uv` 时回退到当前 Python 的 `pip`。

Windows PowerShell 中可用 `Copy-Item` 代替上面的 `cp`。

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

Deep Research 的执行方式：

1. 主 Agent 按研究问题创建一轮 DAG；
2. 同一层的子任务并行执行，子 Agent 通过 `submit_output` 返回结构化发现和来源；
3. Deep Research Skill 指导主 Agent 在每轮后调用状态读取器，只取概览和选定的证据 ID；
4. 主 Agent 根据覆盖情况决定继续检索、分析或启动 critic 审查，最后生成报告。

子 Agent 的最大 LLM 调用次数，以及 `web_researcher` 的搜索和抓取预算，可在 `agent/config.yaml` 中配置。critic 与 Skill 中的来源优先级指导用于提高可追溯性和审查力度，但不构成对报告正确性的保证。

---

## 配置

复制环境变量与配置示例：

```bash
cp .env.example .env
cp agent/config.yaml.example agent/config.yaml
```

API key 放在 `.env` 或系统环境变量中，不应写入或提交 `agent/config.yaml`。完整运行参数见配置文件，包括：

- 主模型与辅助模型的 provider/model
- 工具集与 `safe` / `auto` / `review` 权限模式
- 对话历史压缩和单次工具输出限制
- 子 Agent LLM 调用上限与研究搜索/抓取预算
- Crawl4AI 抓取预览长度、浏览器通道和 `robots.txt` 策略
- MCP server、日志和记忆参数

默认搜索后端是 [Tavily](https://www.tavily.com/)，需要设置 `TAVILY_API_KEY`。也可以切换到 DuckDuckGo 或 Serper，或通过 MCP 添加搜索服务。网页抓取使用 Crawl4AI：完整 Markdown 保存到当前工作区，只向模型返回有界预览。

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

关键组件：

- **`agent/orchestrator/`** — 基于 FSM 的执行流程、技能生命周期、记忆提取，以及围绕 agent 主循环的编排胶水层
- **`agent/memory/`** — 状态导向记忆系统：Fact 存储、Topic 注册、View 编译器、Collision 检测器
- **`agent/tool/basic_tools/tool_plan.py`** — 阻塞式 `create_plan`、DAG 子 Agent 调度、预算与结构化提交
- **`agent/tool/`** — 按领域组织的内置工具与 MCP 工具
- **`agent_types/`** — 预定义子 Agent 配置（`web_researcher`、`analyst`、`critic`），使用 YAML frontmatter
- **`skills/`** — 运行时动态加载的 Markdown 技能（`deep-research`、`code-doc`、`skill-writer`、`system-guide` 等）
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

LINAR 是个人开发中的实验性项目。Agent 工具循环、FSM、DAG 执行、Deep Research、记忆和基础评测链路已有实现，但 API、内部接口和研究策略仍可能变化。

阶段性评测：

- [**DeepResearch Bench**](https://github.com/Ayanami0730/deep_research_bench) RACE（2026-07-16，29 道有效样本）：**Overall 52.42**
  - Comprehensiveness：52.31
  - Insight：52.02
  - Instruction Following：53.71
  - Readability：51.02

29 道题的语言分布：

| 语言 | 数量 |
|------|-----:|
| 中文 | 29 |
| 英文 | 0 |

按 DeepResearch Bench 数据集的原始 `topic` 字段统计：

| 类别 | 数量 |
|------|-----:|
| Science & Technology | 8 |
| Finance & Business | 6 |
| Software Development | 5 |
| Education & Jobs | 4 |
| Health | 3 |
| Literature | 2 |
| History | 1 |

题目内容横跨科技研发、软件工程、产业与金融、地方财政与公共政策、教育就业、健康和人文社科。政策是跨类别主题，并非数据集中的独立 `topic` 标签。

这是 29 道中文有效样本的阶段性结果，不包含英文题，也不是 100 题完整榜单成绩，因此不能单独用于判断英文研究能力或不同模型、配置和代码版本下的固定表现。仓库内的评测脚本支持任务隔离、断点续跑、失败记录与重试，生成答案与后续评分分开执行。

当前边界：

- 工具权限是应用层策略，不是操作系统级沙箱；
- critic、Skill 中的来源优先级指导和引用保留用于增强审查与追溯，不保证事实完全正确；
- MCP、模型 provider 和网页服务的可用性仍取决于本地配置与外部服务。

---

## 许可证

MIT — 参见 [LICENSE](LICENSE)。
