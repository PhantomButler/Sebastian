---
version: "1.0"
last_updated: 2026-05-01
status: implemented
---

# 截图发送工具：capture_screenshot_and_send

*← [Capabilities 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景

`send_file` 让 Agent 发送已有文件。本工具在此基础上新增一步：在后端宿主机上捕获屏幕截图，再通过 `send_file_path` helper 发送给当前对话。

截图工具捕获的是**运行 Sebastian 后端的机器桌面**，不是 Android 设备屏幕。

---

## 2. 范围

**实现内容（P0）**：

- 全屏截图。
- macOS 和 Linux 后端宿主。
- 通过现有 `send_file_path` attachment 链路发送图片。
- 仅暴露给 Sebastian 顶层 Orchestrator，不向 Sub-Agent 开放。
- 确定性失败返回清晰错误。

**不在范围**：区域/窗口/多显示器选择、Android 设备截屏、浏览器截图、DBus portal 捕获、Sub-Agent 访问。

---

## 3. 工具规格

| 属性 | 值 |
|------|-----|
| 位置 | `sebastian/capabilities/tools/screenshot_send/__init__.py` |
| 工具名 | `capture_screenshot_and_send` |
| 权限 | `PermissionTier.HIGH_RISK` |
| 曝光范围 | 仅 Sebastian Orchestrator（`sebastian/orchestrator/sebas.py`），不加入 Sub-Agent `manifest.toml` |

```python
async def capture_screenshot_and_send(
    display_name: str | None = None,
) -> ToolResult:
    ...
```

默认文件名按时间戳生成：`screenshot-20260429-153012.png`。`display_name` 无后缀时自动追加 `.png`。

---

## 4. 权限模型

截图可暴露密码、API Key、私信、浏览器标签页等敏感内容——与发送用户已指定文件不同，这是主动读取可见桌面状态。因此使用 `PermissionTier.HIGH_RISK`，每次调用都需要用户显式批准。

批准文案应明确说明截图来自后端宿主机桌面，不是手机。

---

## 5. 临时文件管理

截图是中间产物，存储在 Sebastian 数据目录下：

```
settings.user_data_dir / "tmp" / "screenshots"
# 默认: ~/.sebastian/data/tmp/screenshots/
```

> 注意：`settings.user_data_dir` = `settings.data_dir / "data"`（layout-v2 结构）。不能直接用 `settings.data_dir` 或 `SEBASTIAN_DATA_DIR`。

目录不由 `ensure_data_dir()` 预创建，工具自己调用：

```python
screenshot_tmp_dir.mkdir(parents=True, exist_ok=True)
```

**不能**写入仓库 workspace、系统 `/tmp`（作为主位置）或 attachment blob 目录。

生命周期：

```
创建 data/tmp/screenshots/
  → 可选：清理 24 小时以上的旧截图文件
  → 捕获 PNG 到 data/tmp/screenshots/
  → 调用 send_file_path 上传/发送
  → finally: 删除临时 PNG
```

正常运行后目录为空。每次捕获前保守清理 24 小时以上的文件。

---

## 6. 复用 send_file_path

截图工具不重复 attachment 上传、artifact 构造、缩略图 URL、session 绑定、SSE 逻辑，全部复用 `send_file_path` helper（来自 `sebastian/capabilities/tools/send_file/__init__.py`）：

```python
# send_file/__init__.py
async def send_file_path(file_path: str, display_name: str | None = None) -> ToolResult:
    ...  # 完整上传逻辑

@tool(name="send_file", ...)
async def send_file(file_path: str, display_name: str | None = None) -> ToolResult:
    return await send_file_path(file_path, display_name)

# screenshot_send/__init__.py
result = await send_file_path(str(screenshot_path), display_name=filename)
```

`send_file_path` 依赖 `get_tool_context()` 获取 `session_id`/`agent_type`，是工具调用栈内部 helper，不是通用上传 API。

返回的 artifact 与普通 `send_file` 图片结果结构相同，Android 无需新 UI 逻辑。

---

## 7. 平台后端

### 7.1 macOS

```bash
/usr/sbin/screencapture -x <output.png>
```

- `-x` 静音（无快门声）
- 缺少 Screen Recording 权限时返回确定性错误
- 命令退出码成功且输出文件存在且 `size_bytes > 0` 才视为成功（部分 macOS 版本权限拒绝时会产生零字节文件）

### 7.2 Linux

无 `DISPLAY` 且无 `WAYLAND_DISPLAY` → 返回明确的 headless 错误。

同时存在 `WAYLAND_DISPLAY` 和 `DISPLAY` → 优先 Wayland 路径（GNOME 等 Wayland 桌面会设 `DISPLAY` 兼容 XWayland，但 X11 工具在此模式可能捕获不完整）。

**X11**：优先 `gnome-screenshot -f <output.png>`，回落 `scrot <output.png>`，都不存在则报错并建议安装。

**Wayland**：优先 `grim <output.png>`，不可用则返回明确错误。

使用 `shutil.which()` 做工具检测。

P0 不实现 DBus portal 捕获。

---

## 8. 实现细节

```python
# 截图命令用参数列表，不用 shell 字符串（防命令注入）
subprocess.run(
    ["/usr/sbin/screencapture", "-x", str(output_path)],
    check=False,
    capture_output=True,
    text=True,
)

# 使用 asyncio.to_thread 避免阻塞事件循环
# 不用 asyncio.create_subprocess_exec（Linux 有 subprocess watcher 清理 hang 问题）
result = await asyncio.to_thread(subprocess.run, command, ...)
```

---

## 9. 失败处理

所有确定性失败返回 `ToolResult(ok=False, error=...)`，含失败原因和下一步建议，并明确禁止自动重试。

| 失败场景 | error 文本模式 |
|---------|--------------|
| macOS 缺 Screen Recording 权限 | `Screen capture permission is not granted on macOS. Do not retry automatically; ask the user to grant Screen Recording permission...` |
| Linux headless 无图形会话 | `Linux screenshot requires a graphical session; DISPLAY/WAYLAND_DISPLAY is missing. Do not retry automatically; tell the user screenshots are unavailable...` |
| Linux 无可用截图后端 | `No supported Linux screenshot backend found. Do not retry automatically; ask the user to install gnome-screenshot, scrot, or grim...` |
| 截图命令失败 | `Screenshot command failed: <stderr>. Do not retry automatically; tell the user the screen could not be captured.` |
| 截图成功但 send_file 失败 | `Screenshot was captured but could not be sent: <error>. Do not retry automatically; tell the user the screenshot could not be attached.` |

临时文件删除失败只记录日志，不影响上传成功的结果。

---

## 10. 测试覆盖

主要测试文件：`tests/unit/capabilities/test_screenshot_send_tool.py`

关键场景：

- macOS 构建正确的 `screencapture` 命令
- macOS 命令退出码 0 但文件零字节 → 视为失败
- Linux X11 优先 `gnome-screenshot`，回落 `scrot`
- Linux Wayland 使用 `grim`
- 同时有 `WAYLAND_DISPLAY` 和 `DISPLAY` 时走 Wayland 路径
- Headless Linux 返回确定性错误
- 无可用 Linux 后端返回确定性错误
- 成功捕获后调用 `send_file_path` helper
- 成功后临时 PNG 被删除
- send 失败后临时 PNG 也被删除
- `display_name` 无后缀自动追加 `.png`
- 工具 permission_tier 为 `HIGH_RISK`

---

*← [Capabilities 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
