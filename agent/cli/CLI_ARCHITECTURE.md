# Lily CLI 架构说明

## 概览

CLI 层提供基于 prompt_toolkit 的 REPL 终端，与 Agent 通过 JSON 事件流通信，使用 Rich 进行渲染。

```
用户输入 → LilyTerminal → agent.add_user_message()
                            agent.process_with_llm()
                                │
                                ▼  emit(JSON event)
                          _on_event(event)
                                │
                                ▼
                          Rich Console 输出
```

## 文件结构

```
agent/cli/
├── __init__.py         # 包标记
├── terminal.py         # 主 REPL 循环、事件处理、命令系统
├── style.yaml          # 颜色主题配置（UI 可定制）
├── style_loader.py     # 样式加载器（合并 YAML + 硬编码默认值）
├── CLI_ARCHITECTURE.md # 本文档 — 架构 + 开发指南
└── CLI_SETTINGS.md     # 配置参考
```

## 核心组件

### terminal.py

**`_CommandCompleter`** — Tab 补全器
- 仅在输入以 `/` 开头时激活
- 支持基础命令补全和子参数补全（如 `/reasoning hide|full`）

**`LilyTerminal`** — 主终端类
- **`__init__`**: 接入 Agent 实例，加载样式配置，初始化渲染状态
- **`_on_event`**: 事件驱动渲染器，处理 7 种事件类型（见下文事件流）
- **`_handle_command`**: 内置命令处理器

**入口函数 `main()`**:
1. 从配置文件加载工具集
2. 注入 prompt_toolkit 的密码输入回调
3. 创建 Agent → LilyTerminal → 进入 REPL 循环

### style_loader.py

- 读取 `style.yaml`，与 `DEFAULTS` 字典深度合并
- 保证即使 YAML 文件缺失，每个键都有默认值
- banner/console/mode_colors 三层结构

## 事件流

Agent 调用 `emit()` 发送 JSON 事件，`_on_event` 按类型分发：

| 事件类型 | 触发时机 | 渲染行为 |
|---|---|---|
| `start` | LLM 开始响应 | 重置所有累计状态，记录开始时间 |
| `token` | 流式文本块 | 去除 [turn N] 标记，处理 **bold**，打印到控制台 |
| `reasoning_token` | 推理内容块 | 仅 `show_reasoning: full` 时打印（dim italic 样式） |
| `usage` | token 用量信息 | 累计，在 `complete` 时显示 |
| `tool_call` | 工具调用 | 按模式显示：hide/工具名/参数预览 |
| `tool_result` | 工具执行结果 | 仅在 `detailed` 模式显示结果摘要 |
| `error` | 错误信息 | 红色打印 |
| `done` | 单次 LLM 调用结束 | 换行 |
| `complete` | 所有 LLM 调用结束 | 打印统计栏（耗时 + token 进度条） |

## 命令系统

所有命令以 `/` 开头，在 `_handle_command` 中处理：

| 命令 | 功能 |
|---|---|
| `/exit`, `/quit` | 退出终端 |
| `/help` | 显示命令帮助 |
| `/reset`, `/clear` | 新会话（调用 `agent.reset_session()`） |
| `/reasoning [mode]` | 设置/切换推理显示模式 |
| `/tool_calls [mode]` | 设置/切换工具调用显示模式 |
| `/sessions` | 列出所有会话 + 交互式选择器 |
| `/session [id]` | 查看/切换会话 |
| `/session rename <id> <title>` | 重命名会话 |
| `/session delete <id>` | 删除会话 |

## 特殊渲染处理

### Bold 标记
流式文本中的 `**...**` 被实时解析为 Rich bold 样式。维护一个 `_pending` 缓冲区处理跨 chunk 的标记分割。

### 统计栏
每次完整响应后显示：
```
⏱ 12.3s  │  Tokens: 1.2K / 1.0M  [####       ] 20%
```
颜色根据 token 使用率动态变化（绿 < 50% < 黄 < 70% < 红）。

### Logo 渲染
使用分段标记系统，每段带样式键，从 style.yaml 的 banner 部分取色。CJK 字符宽度通过 `cell_len` 计算确保对齐。

---

# 基于 CLI 的开发指南

## 添加新命令

三步完成：

**1. 在 `_handle_command` 中添加分支**

`terminal.py:431` 的 `_handle_command` 方法是一个 if-elif 链，在 `return False` 前加入新分支：

```python
if cmd.startswith("/mycommand"):
    parts = cmd.split(maxsplit=1)
    # ... 处理逻辑 ...
    if something:
        self.console.print("结果")
    else:
        e = self.s("error")
        self.console.print(f"[{e}]错误信息[/{e}]")
    return True  # 返回 True 表示命令已处理
```

**2. 在 `_CommandCompleter` 中注册补全**

在 `commands` 列表中添加新命令名：

```python
commands = [
    "/exit", "/quit", "/help", "/reset", "/clear",
    "/reasoning", "/tool_calls", "/sessions", "/session",
    "/mycommand",  # ← 添加
]
```

如需子参数补全，在 `if " " in text:` 块中添加分支。

**3. 在 `/help` 中列出**

```python
self.console.print("  /mycommand [arg]       Description")
```

### 最佳实践
- 命令用 `/` 前缀，与普通消息区分
- 返回值一律用 `True`（表示命令已消费），不要 `return False` 让用户消息进入 LLM
- 错误信息使用 `self.s("error")` 获取颜色样式
- 调用 Agent 方法或 DB 函数处理逻辑，不要在命令处理器中直接写业务逻辑

## 添加新事件类型

如果需要 Agent 发送 CLI 当前不支持的事件：

**1. 在 Agent 端定义事件**

```python
self.emit({"type": "my_event", "data": {...}})
```

**2. 在 `_on_event` 中添加处理**

```python
elif etype == "my_event":
    data = event["data"]
    # 渲染逻辑
```

### 现有事件处理参考
- 流式文本：`token` 事件 → `_process_output()` 处理 bold 后 `console.print(end="")`
- 工具调用：`tool_call` 事件 → 按 `self.tool_calls_mode` 决定显示级别
- 所有事件共用的 `self._print_header()` 确保在响应首次出现时打印 `⚡ Lily` 头部

## 添加新的显示模式

以 `reasoning` 模式为模板（`terminal.py:468-489`）：

**1. 定义模式枚举**（文件顶部）

```python
MY_MODE = ("mode_a", "mode_b")
```

**2. 在 `__init__` 中读取默认值**

```python
default_m = cfg.get("show_myfeature", "mode_a")
self.my_mode = default_m if default_m in MY_MODE else "mode_a"
```

**3. 添加切换命令**

```python
if cmd.startswith("/myfeature"):
    parts = cmd.split(maxsplit=1)
    if len(parts) == 1:
        # toggle
        current_idx = MY_MODE.index(self.my_mode)
        next_idx = (current_idx + 1) % len(MY_MODE)
        self.my_mode = MY_MODE[next_idx]
    else:
        arg = parts[1].lower()
        if arg in MY_MODE:
            self.my_mode = arg
        else:
            self.console.print(f"Invalid. Use: {' | '.join(MY_MODE)}")
            return True
    self.console.print(f"Set to: {self.my_mode}")
    return True
```

**4. 在 `_on_event` 中根据模式分发**

```python
if self.my_mode == "mode_a":
    # 方式 A
elif self.my_mode == "mode_b":
    # 方式 B
```

## 修改样式/颜色

编辑 `style.yaml` 键值，无需改动 Python 代码：
- `banner.*` — 欢迎屏幕颜色
- `console.*` — 各类 UI 元素的颜色
- `mode_colors.*` — 模式名的颜色标签

`style_loader.py` 会深度合并 YAML 与硬编码默认值，缺失的键自动回退。

## 添加新的交互式选择器

参考 `/sessions` 的实现模式（`terminal.py:537-568`）：

```python
from prompt_toolkit.shortcuts import prompt as pt_prompt
from prompt_toolkit.completion import Completer, Completion

class _MyPicker(Completer):
    def __init__(self, items):
        self.items = items
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        for item in self.items:
            if not text or str(item["id"]).startswith(text):
                yield Completion(str(item["id"]),
                    start_position=-len(text),
                    display=f"#{item['id']}  {item['label']}")

try:
    result = pt_prompt("Select (or Enter to cancel): ",
        completer=_MyPicker(items), complete_while_typing=True)
    if result and result.strip():
        # 处理选择
except (KeyboardInterrupt, EOFError):
    pass  # 用户取消
```

## 调试技巧

- **查看原始事件流**：在 `_on_event` 开头加 `print(event)` 到 stderr
- **测试命令处理**：直接调用 `cli._handle_command("/command arg")`
- **样式验证**：修改 `style.yaml` 后重启终端即可看到效果
- **常见问题**：
  - `_process_output` 中的 `_pending` 缓冲区不释放 → 检查是否存在未闭合的 `**`
  - 事件顺序错误 → Agent 的 `emit()` 调用顺序决定了渲染顺序
  - CJK 对齐问题 → 使用 `cell_len()` 而非 `len()` 计算宽度
