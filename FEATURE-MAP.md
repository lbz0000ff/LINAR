# EchoLily 功能对照表

> 用途：对比 TUI 已有的功能和 GUI（WebUI）当前的实现状态，确定 GUI 开发优先级。

---

## 1. 消息流

| 功能 | TUI | GUI WebUI | 后端支持 |
|------|:---:|:---------:|:--------:|
| 发送消息 | ✅ | ✅ | ✅ `message` |
| 流式 Token 输出 | ✅ | ✅ | ✅ `token` |
| 思考过程显示 | ✅ 灰色折叠 | ✅ 灰色折叠 | ✅ `reasoning_token` |
| 工具调用显示 | ✅ `⚙ xxx` | ✅ | ✅ `tool_call` |
| 工具结果显示 | ✅ `→ 结果` | ✅ | ✅ `tool_result` |
| 错误显示 | ✅ 红字 | ✅ | ✅ `error` |
| 完成/就绪状态 | ✅ | ✅ | ✅ `done`/`ready` |
| 计划（DAG）显示 | ✅ 分步 | ❌ | ✅ `plan_start/plan/plan_complete` |
| Token 用量统计 | ✅ 底部 | ❌ | ✅ `usage` |
| 异步任务完成通知 | ✅ | ❌ | ✅ `promise_resolved` |
| 技能加载通知 | ✅ | ❌ | ✅ `skill_loaded` |
| BTW/Steer 提示 | ✅ | ❌ | ❌ 纯前端 |

## 2. 交互功能

| 功能 | TUI | GUI WebUI | 后端支持 |
|------|:---:|:---------:|:--------:|
| ask_user 提问 | ✅ 内联输入 | ❌ | ✅ `_prompt_user` |
| 工具权限审批 | ✅ 弹窗 | ❌ | ✅ `_confirm_tool` |
| 文件上传 | ❌（TUI 无） | ✅ | ✅ `/upload` |
| 图片发送 | ❌（TUI 无） | ⚠️ 不完善 | ✅ `vision_query` |
| 图片生成显示 | ❌ | ❌ | ✅ comfyui-mcp |
| 中断/停止 | ✅ Ctrl+C | ✅ 中止按钮 | ✅ `stop` |
| 输入框展开 | ❌（单行） | ✅ | ❌ 纯前端 |

## 3. 会话管理

| 功能 | TUI | GUI WebUI | 后端支持 |
|------|:---:|:---------:|:--------:|
| 会话列表 | ✅ | ✅ | ✅ `list_sessions` |
| 切换会话 | ✅ `/session N` | ✅ 点击 | ✅ `switch_session`+`get_session` |
| 新建会话 | ✅ 自动 | ✅ | ✅ `new_session` |
| 会话重命名 | ✅ `/session rename` | ❌ | ❌（需加 `rename_session`）|
| 会话删除 | ✅ `/session delete` | ❌ | ❌（需加 `delete_session`）|
| 会话搜索 | ✅ 模糊搜索 | ✅ 设计稿有 | ❌ 纯前端 |

## 4. 系统功能

| 功能 | TUI | GUI WebUI | 后端支持 |
|------|:---:|:---------:|:--------:|
| 设置（配置编辑） | ✅ 文件修改 | ✅ 基础表单 | ✅ `get_config_json`/`save_config` |
| 暗色模式 | ❌（TUI 无） | ✅ CSS 变量 | ❌ 纯前端 |
| MCP 热加载 | ✅ `/reload_mcp` | ❌ | ✅ 已有 `/reload_mcp` |
| 后台任务列表 | ✅ `/list_jobs` | ❌ | ✅ `promise` 工具 |
| 显示模式切换 | ✅ `/reasoning` `/tool_calls` | ❌ | ❌ 纯前端 |
| 技能查看 | ✅ `skill_view` | ❌ | ✅ `skill_view` 工具 |
| 日志查看 | ✅ `/logging` | ❌（浏览器自带）| ❌ |

## 5. 消息操作

| 功能 | TUI | GUI WebUI | 后端支持 |
|------|:---:|:---------:|:--------:|
| 消息复制 | ❌ | ⚠️ 设计稿有 UI | ❌ 纯前端 |
| 重新生成 | ❌ | ❌ 设计稿有 UI | ❌ 需后端支持 |
| 暂停编辑 | ❌ | ❌ 设计稿有 UI | ❌ 需后端支持 |

## 6. 富内容渲染

| 功能 | TUI | GUI WebUI | 后端支持 |
|------|:---:|:---------:|:--------:|
| Markdown | ❌（纯文本）| ✅ marked.js | ❌ 纯前端 |
| 数学公式 | ❌ | ✅ KaTeX | ❌ 纯前端 |
| Mermaid 图表 | ❌ | ✅ mermaid.js | ❌ 纯前端 |
| 代码高亮 | ❌ | ✅ marked.js 自带 | ❌ 纯前端 |

---

## 图例

- ✅ = 已完成
- ⚠️ = 部分完成
- ❌ = 未实现
