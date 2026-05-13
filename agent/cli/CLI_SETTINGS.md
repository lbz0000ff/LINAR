# Lily CLI 配置参考

## 颜色主题 — style.yaml

位于 `agent/cli/style.yaml`，用于定制终端 UI 颜色。所有值使用 Rich 颜色语法（如 `"bold cyan"`, `"grey62"`, `"dim"`, `"red"`）。

```yaml
# UI color theme for Lily Terminal

banner:
  border: "grey"         # 欢迎横幅的边框
  lily: "grey85"         # "LILY" logo 文字
  i: "red"               # logo 中 "i" 字母的强调色
  shadow: "grey"         # logo 的阴影部分
  title: "yellow"        # "version x.x" 标题
  hint: "grey62"         # "Type /help" 提示

console:
  header: "bold cyan"    # "⚡ Lily" 响应头部
  reasoning: "dim italic" # 推理内容样式
  tool_name: "grey85"    # 工具名
  tool_detail: "grey62"  # 工具参数/结果详情
  error: "red"           # 错误信息
  stats_dim: "dim"       # 统计栏分隔符
  stats_good: "bold green"  # 低 token 用量
  stats_warn: "bold yellow" # 中等 token 用量
  stats_bad: "red"       # 高 token 用量
  new_session: "dim"     # 新会话提示
  goodbye: "red"         # 退出提示

mode_colors:
  reasoning:
    hide: "red"
    full: "yellow"
  tool_calls:
    hide: "red"
    show_tools: "cyan"
    detailed: "yellow"
```

不配置某个字段时，`style_loader.py` 中的 `DEFAULTS` 字典（`agent/cli/style_loader.py:13-46`）会提供上述默认值。

### 颜色方案切换

可以准备多个 YAML 文件，需要时覆盖 `style.yaml` 即可。格式必须保持一致，缺失的字段会自动从默认值补充。

## config.yaml CLI 相关配置项

```yaml
# agent/config.yaml 中的 CLI 相关项

show_reasoning: "hide"      # "hide" | "full" — 是否显示 LLM 推理过程
show_tool_calls: "detailed" # "hide" | "show_tools" | "detailed" — 工具调用显示级别
show_tool_calls: "detailed" # "hide" | "show_tools" | "detailed" — 工具调用显示级别
```

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `show_reasoning` | `"hide"` | 终端启动时的默认推理显示模式 |
| `show_tool_calls` | `"detailed"` | 终端启动时的默认工具调用显示模式 |

> 统计栏的 token 上限读取自 `llm.max_tokens`，不再有独立配置项。

这些值在 `LilyTerminal.__init__()` 中读取，运行时可通过 `/reasoning` 和 `/tool_calls` 命令覆盖。

## Rich 颜色参考

常用颜色值：
- 基础色：`red`, `green`, `yellow`, `blue`, `cyan`, `magenta`, `white`, `black`
- 亮色：`bright_red`, `bright_green`, `bright_blue` 等
- 灰度：`grey`, `grey11`, `grey23`, `grey35`, `grey46`, `grey58`, `grey62`, `grey69`, `grey78`, `grey85`, `grey93`
- 样式修饰：`bold`, `dim`, `italic`, `underline`, `blink`, `reverse`, `strike`
- 组合：`"bold italic cyan"`, `"dim grey62"` 等
