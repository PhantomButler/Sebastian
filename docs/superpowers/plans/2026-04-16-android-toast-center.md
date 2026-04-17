# ToastCenter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Android App 中新建公共 Toast 入口 `ToastCenter`，内置"同 key 1.5s 节流"与"进程内同时刻最多一条"两层防护，替换现有两处手写 Toast 调用点。

**Architecture:** `object ToastCenter` 单进程单例，暴露 `show(context, message, key, throttleMs, duration)`。三个 `internal` lambda 桩点（`clock` / `mainExecutor` / `toastFactory`）支持 JVM 单元测试无需 Robolectric。两处 UI 调用点移除 `remember<Toast?>` 样板直接调用 `ToastCenter.show(...)`。

**Tech Stack:** Kotlin, Android `Toast` / `Handler(mainLooper)`, JUnit4, Mockito-Kotlin（`org.mockito.kotlin.*`，仓库现有栈）。

**Spec:** `docs/superpowers/specs/2026-04-16-android-toast-center-design.md`

**工作目录：** 全程在 `dev` 分支直接开发，不拉新分支（符合 `CLAUDE.md` 分支模型）。

---

## 文件结构

| 路径 | 动作 | 职责 |
|---|---|---|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/ToastCenter.kt` | **新建** | 公共 Toast 入口（object 单例，~50 行） |
| `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/common/ToastCenterTest.kt` | **新建** | 4 用例 + 状态重置（~80 行） |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt` | **改** | 删 `alreadyInSessionToast` 样板，换 `ToastCenter.show(...)` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` | **改** | 删 `newSessionToast` 样板，换 `ToastCenter.show(...)` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/README.md` | **改** | 目录结构 + ToastCenter 段 + 修改导航表 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/README.md` | **改** | 修改导航表加一行 |
| `ui/mobile-android/README.md` | **改** | 修改导航表加一行 |

### Spec 实现差异（说明）

Spec §5 未提到 object 单例在单元测试间的状态隔离。Plan 新增 `internal fun resetForTest()`（`@VisibleForTesting`）清空 `lastShownAt` 与 `currentToast`，仅用于测试 `@Before`。这是实现层面的测试钩子，不改变 Spec 行为契约。

---

## Task 1：实现 ToastCenter（TDD）

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/ToastCenter.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/common/ToastCenterTest.kt`

- [ ] **Step 1.1：新建 ToastCenter 骨架**

创建 `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/ToastCenter.kt`，内容如下（只含签名与桩点，`show` 函数体为空让测试全部 fail）：

```kotlin
package com.sebastian.android.ui.common

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.widget.Toast
import androidx.annotation.VisibleForTesting

object ToastCenter {
    private val lastShownAt = HashMap<String, Long>()
    private var currentToast: Toast? = null

    @VisibleForTesting internal var clock: () -> Long = { SystemClock.uptimeMillis() }
    @VisibleForTesting internal var mainExecutor: (Runnable) -> Unit =
        { Handler(Looper.getMainLooper()).post(it) }
    @VisibleForTesting internal var toastFactory: (Context, CharSequence, Int) -> Toast =
        { ctx, msg, dur -> Toast.makeText(ctx, msg, dur) }

    fun show(
        context: Context,
        message: CharSequence,
        key: String = message.toString(),
        throttleMs: Long = 1500L,
        duration: Int = Toast.LENGTH_SHORT,
    ) {
        // Step 1.4 填充
    }

    @VisibleForTesting
    internal fun resetForTest() {
        synchronized(this) {
            lastShownAt.clear()
            currentToast = null
        }
    }
}
```

- [ ] **Step 1.2：写 4 个测试**

创建 `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/common/ToastCenterTest.kt`：

```kotlin
package com.sebastian.android.ui.common

import android.content.Context
import android.widget.Toast
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.doReturn
import org.mockito.kotlin.mock
import org.mockito.kotlin.stub
import org.mockito.kotlin.verify

class ToastCenterTest {

    private lateinit var context: Context
    private var fakeNow: Long = 0L
    private val createdToasts = mutableListOf<Toast>()

    private val origClock = ToastCenter.clock
    private val origExecutor = ToastCenter.mainExecutor
    private val origFactory = ToastCenter.toastFactory

    @Before
    fun setup() {
        context = mock { on { applicationContext } doReturn it }
        fakeNow = 0L
        createdToasts.clear()
        ToastCenter.resetForTest()
        ToastCenter.clock = { fakeNow }
        ToastCenter.mainExecutor = { it.run() }
        ToastCenter.toastFactory = { _, _, _ ->
            mock<Toast>().also { createdToasts += it }
        }
    }

    @After
    fun tearDown() {
        ToastCenter.clock = origClock
        ToastCenter.mainExecutor = origExecutor
        ToastCenter.toastFactory = origFactory
        ToastCenter.resetForTest()
    }

    @Test
    fun `same key within throttle window is dropped`() {
        ToastCenter.show(context, "hi")
        fakeNow = 500L  // < 1500ms
        ToastCenter.show(context, "hi")

        assertEquals(1, createdToasts.size)
    }

    @Test
    fun `same key after throttle window is shown`() {
        ToastCenter.show(context, "hi")
        fakeNow = 1600L  // > 1500ms
        ToastCenter.show(context, "hi")

        assertEquals(2, createdToasts.size)
    }

    @Test
    fun `different keys pass independently`() {
        ToastCenter.show(context, "hi", key = "a")
        ToastCenter.show(context, "hi", key = "b")

        assertEquals(2, createdToasts.size)
    }

    @Test
    fun `second show cancels previous toast`() {
        ToastCenter.show(context, "first", key = "a")
        ToastCenter.show(context, "second", key = "b")

        verify(createdToasts[0]).cancel()
    }
}
```

- [ ] **Step 1.3：跑测试，确认 4 条全部 FAIL**

Run:
```bash
cd ui/mobile-android && ./gradlew test --tests "com.sebastian.android.ui.common.ToastCenterTest"
```
Expected: 4 tests, 4 failures（都因 `createdToasts.size == 0`，`show` 函数体尚未实现）。

- [ ] **Step 1.4：填充 `show` 函数体**

把 Step 1.1 创建文件里 `show` 函数体（现在是空）替换为：

```kotlin
    fun show(
        context: Context,
        message: CharSequence,
        key: String = message.toString(),
        throttleMs: Long = 1500L,
        duration: Int = Toast.LENGTH_SHORT,
    ) {
        val now = clock()
        synchronized(this) {
            val last = lastShownAt[key]
            if (last != null && now - last < throttleMs) return
            lastShownAt[key] = now
        }
        val app = context.applicationContext
        mainExecutor {
            currentToast?.cancel()
            currentToast = toastFactory(app, message, duration).also { it.show() }
        }
    }
```

- [ ] **Step 1.5：跑测试，确认全部 PASS**

Run:
```bash
cd ui/mobile-android && ./gradlew test --tests "com.sebastian.android.ui.common.ToastCenterTest"
```
Expected: 4 tests, 0 failures。

再跑一次完整 JVM 测试确认无回归：
```bash
cd ui/mobile-android && ./gradlew test
```
Expected: BUILD SUCCESSFUL。

- [ ] **Step 1.6：commit**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/ToastCenter.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/ui/common/ToastCenterTest.kt
git commit -m "$(cat <<'EOF'
feat(android): 新增 ToastCenter 统一 Toast 入口（节流 + 单例显示）

内置两层防护：同 key 1.5s 节流 + 进程内同时刻最多一条。
通过 internal 桩点（clock / mainExecutor / toastFactory）
支持纯 JVM 单元测试。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2：迁移 MainActivity 调用点

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt`

- [ ] **Step 2.1：删除 `import android.widget.Toast`（行 18）**

`ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt` 第 18 行：

```kotlin
import android.widget.Toast
```

删除此行。

- [ ] **Step 2.2：添加 ToastCenter 导入**

在 import 区（与其他 `com.sebastian.android.*` 导入同位置，按字母序）添加：

```kotlin
import com.sebastian.android.ui.common.ToastCenter
```

- [ ] **Step 2.3：删除 `alreadyInSessionToast` 局部状态（行 136-137）**

找到这两行并整段删除：

```kotlin
    // 单例 Toast：连点时先 cancel 上一个，避免排队连续弹
    var alreadyInSessionToast by remember { mutableStateOf<Toast?>(null) }
```

- [ ] **Step 2.4：替换使用处（行 259-264）**

把下面这段：

```kotlin
                if (approval.sessionId == currentViewingSessionId) {
                    alreadyInSessionToast?.cancel()
                    alreadyInSessionToast = Toast.makeText(
                        context,
                        "已在目标会话",
                        Toast.LENGTH_SHORT,
                    ).also { it.show() }
                    return@GlobalApprovalBanner
                }
```

替换为：

```kotlin
                if (approval.sessionId == currentViewingSessionId) {
                    ToastCenter.show(context, "已在目标会话")
                    return@GlobalApprovalBanner
                }
```

- [ ] **Step 2.5：编译通过**

Run:
```bash
cd ui/mobile-android && ./gradlew assembleDebug
```
Expected: BUILD SUCCESSFUL。若报"unused import"需清理残留。

- [ ] **Step 2.6：全量 JVM 测试无回归**

Run:
```bash
cd ui/mobile-android && ./gradlew test
```
Expected: BUILD SUCCESSFUL。

- [ ] **Step 2.7：commit**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt
git commit -m "$(cat <<'EOF'
refactor(android): MainActivity 迁移至 ToastCenter

移除 alreadyInSessionToast 本地状态与 cancel 样板，
统一走 ToastCenter.show。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3：迁移 ChatScreen 调用点

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`

- [ ] **Step 3.1：删除 `import android.widget.Toast`（行 45）**

`ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` 第 45 行：

```kotlin
import android.widget.Toast
```

删除此行。

- [ ] **Step 3.2：添加 ToastCenter 导入**

在 import 区（与其他 `com.sebastian.android.*` 导入同位置，按字母序）添加：

```kotlin
import com.sebastian.android.ui.common.ToastCenter
```

- [ ] **Step 3.3：删除 `newSessionToast` 局部状态（行 154-155）**

找到这两行并整段删除：

```kotlin
            // 单例 Toast：连点时先 cancel 上一个，避免排队连续弹
            var newSessionToast by remember { mutableStateOf<Toast?>(null) }
```

- [ ] **Step 3.4：替换使用处（行 292-301 内的 `if` 分支）**

把下面这段：

```kotlin
                                        if (chatState.messages.isEmpty()) {
                                            newSessionToast?.cancel()
                                            newSessionToast = Toast.makeText(
                                                context,
                                                "Already in a new chat",
                                                Toast.LENGTH_SHORT,
                                            ).also { it.show() }
                                        } else {
                                            chatViewModel.newSession()
                                        }
```

替换为：

```kotlin
                                        if (chatState.messages.isEmpty()) {
                                            ToastCenter.show(context, "Already in a new chat")
                                        } else {
                                            chatViewModel.newSession()
                                        }
```

- [ ] **Step 3.5：编译通过**

Run:
```bash
cd ui/mobile-android && ./gradlew assembleDebug
```
Expected: BUILD SUCCESSFUL。

- [ ] **Step 3.6：全量 JVM 测试无回归**

Run:
```bash
cd ui/mobile-android && ./gradlew test
```
Expected: BUILD SUCCESSFUL。

- [ ] **Step 3.7：commit**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
git commit -m "$(cat <<'EOF'
refactor(android): ChatScreen 迁移至 ToastCenter

移除 newSessionToast 本地状态与 cancel 样板，
统一走 ToastCenter.show。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4：更新三个 README

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/README.md`
- Modify: `ui/mobile-android/README.md`

- [ ] **Step 4.1：更新 `common/README.md` 目录结构**

打开 `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/README.md`，在目录结构代码块中，在 `SebastianIcons.kt` 行与 `glass/` 行之间插入 `ToastCenter.kt` 行（保持按字母序，T 在 S 之后）：

原目录结构块（行 9-18）：

```text
common/
├── AnimationTokens.kt      # 全局动画时长常量
├── ErrorBanner.kt          # 错误横幅（可选操作按钮）
├── GlobalApprovalBanner.kt # 全局审批横幅（悬浮，覆盖所有页面）
├── MarkdownDefaults.kt     # Markdown 颜色/排版/组件配置（含代码块语法高亮）
├── MarkdownView.kt         # 纯 Compose Markdown 渲染组件
├── SebastianIcons.kt       # 自定义图标集（ImageVector 懒加载）
└── glass/                  → [glass/README.md](glass/README.md)  # 液态玻璃组件库
```

改为：

```text
common/
├── AnimationTokens.kt      # 全局动画时长常量
├── ErrorBanner.kt          # 错误横幅（可选操作按钮）
├── GlobalApprovalBanner.kt # 全局审批横幅（悬浮，覆盖所有页面）
├── MarkdownDefaults.kt     # Markdown 颜色/排版/组件配置（含代码块语法高亮）
├── MarkdownView.kt         # 纯 Compose Markdown 渲染组件
├── SebastianIcons.kt       # 自定义图标集（ImageVector 懒加载）
├── ToastCenter.kt          # 公共 Toast 入口（节流 + 同时刻最多一条）
└── glass/                  → [glass/README.md](glass/README.md)  # 液态玻璃组件库
```

- [ ] **Step 4.2：在 `common/README.md` 新增 `### ToastCenter` 段落**

在 "### `glass/`" 段落**之前**（即现有 `### SebastianIcons` 段落之后，`### glass/` 段落之前）插入：

````markdown
### `ToastCenter`

统一的一次性 Toast 入口。内置两层防抖：

1. **节流**：同 `key`（默认为 `message` 本身）在 `throttleMs`（默认 1500ms）内重复调用被丢弃
2. **同时刻最多一条**：进程范围内只持有一个 Toast 引用，新调用先 cancel 再显示

```kotlin
import com.sebastian.android.ui.common.ToastCenter

// 最简：同文案 1.5s 内只弹一次
ToastCenter.show(context, "已在目标会话")

// 同文案不同语义，用 key 区分
ToastCenter.show(context, "已在目标会话", key = "already-in-session")

// 自定义节流窗口
ToastCenter.show(context, message = "...", throttleMs = 3000L)
```

非 Composable 处（ViewModel / 回调）也可直接调用，内部只持 `applicationContext`，不泄漏 Activity。

**禁止直接 `Toast.makeText(...).show()`**——所有一次性提示走 ToastCenter，以保证节流和单例显示。

````

- [ ] **Step 4.3：更新 `common/README.md` 修改导航表**

在修改导航表 "| 改动画时长全局常量 | `AnimationTokens.kt` |" 那一行**之后**插入新的一行：

```markdown
| 弹一次性 Toast 提示（防重复 + 同时刻最多一条） | `ToastCenter.kt` |
```

- [ ] **Step 4.4：更新 `ui/README.md` 修改导航表**

打开 `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/README.md`，在修改导航表 "| 改 Markdown 渲染视图 | \`common/MarkdownView.kt\` |" 那一行**之后**插入：

```markdown
| 弹一次性 Toast 提示 | `common/ToastCenter.kt` |
```

- [ ] **Step 4.5：更新 `ui/mobile-android/README.md` 修改导航表**

打开 `ui/mobile-android/README.md`，在修改导航表 "| 改错误 Banner | \`ui/common/ErrorBanner.kt\` |" 那一行**之后**插入：

```markdown
| 弹一次性 Toast 提示 | `ui/common/ToastCenter.kt` |
```

- [ ] **Step 4.6：commit**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/README.md \
        ui/mobile-android/app/src/main/java/com/sebastian/android/ui/README.md \
        ui/mobile-android/README.md
git commit -m "$(cat <<'EOF'
docs(android): README 补充 ToastCenter 用法与修改导航

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## 手动验证 Checklist（交付给用户执行）

单测绿灯 + 编译通过后，按 `memory` 记录"Android 改动跑完单测即收手，install 由用户自己做"，以下步骤**不**由 agent 执行：

- [ ] `cd ui/mobile-android && ./gradlew installDebug` 装入当前模拟器
- [ ] **场景 A（MainActivity 路径）**：触发一条审批通知指向当前 session；在主对话页快速连点横幅的"查看详情"按钮 5+ 次 → 应只看到一次 Toast `"已在目标会话"`，不连弹、不排队
- [ ] **场景 B（ChatScreen 路径）**：当前是空白新会话，在输入区底部快速连点"新对话"按钮 5+ 次 → 应只看到一次 Toast `"Already in a new chat"`
- [ ] **场景 C（跨 key 单例显示）**：场景 A 与场景 B 交替快速触发 → 后一次应立即替换前一次，不会两条 Toast 排队等待
- [ ] **场景 D（节流窗口恢复）**：场景 A 触发一次 → 等 2 秒 → 再触发一次 → 第二次应正常显示

---

## Self-Review

**1. Spec coverage**

| Spec 段 | Plan 覆盖 |
|---|---|
| §3 API 签名 | Task 1 Step 1.1 + 1.4 |
| §4 行为契约（节流） | Task 1 Step 1.2 用例 1/2 + Step 1.4 实现 |
| §4 单例显示 | Task 1 Step 1.2 用例 4 + Step 1.4 实现 |
| §4 主线程安全 | Step 1.1 `mainExecutor` 桩，生产用 `Handler(mainLooper).post` |
| §4 context 防泄漏 | Step 1.4 `context.applicationContext` |
| §5 内部结构 | Step 1.1 + 1.4 的代码完全对应 |
| §6 MainActivity 迁移 | Task 2 |
| §6 ChatScreen 迁移 | Task 3 |
| §6.5 3 份 README 更新 | Task 4 |
| §7 测试（4 用例） | Task 1 Step 1.2 |
| §9 验收 | 手动验证 Checklist |

**2. Placeholder scan：** 无 TODO / TBD / "add appropriate" / "implement later"。所有代码步骤均给出完整可粘贴代码。

**3. Type consistency：** `show` 签名在 Step 1.1 与 Step 1.4 完全一致；测试桩字段名 `clock` / `mainExecutor` / `toastFactory` 与 `resetForTest()` 在测试与实现文件中一致；迁移 Task 2/3 调用的 `ToastCenter.show(context, "...")` 与 Task 1 签名匹配（使用默认 `key`/`throttleMs`/`duration`）。
