---
integrated_to: mobile/toast-center.md
integrated_at: 2026-04-23
---

# Android ToastCenter 公共组件设计

- 状态：Draft
- 日期：2026-04-16
- 范围：`ui/mobile-android/`

## 1. 背景与目标

Android App 内目前有两处一次性 Toast 提示：

| 位置 | 场景 | 文案 |
|---|---|---|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt` | 审批横幅点击时用户已在目标会话 | "已在目标会话" |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` | 点"新对话"时用户已是空白新对话 | "Already in a new chat" |

两处都各自维护 `var xxxToast by remember { mutableStateOf<Toast?>(null) }`，`show` 前 `cancel` 上一条，样板重复且只解决了「不排队」问题——用户连点仍会看到 Toast 不停闪烁重弹。

抽取公共 `ToastCenter`，一次性解决两个问题：

1. **时间窗口节流**：同 `key` 在 `throttleMs` 内重复调用被丢弃
2. **同时刻最多一条**：进程内新 Toast 先 cancel 旧的再显示

## 2. 非目标

- 不替换 Snackbar。`ProviderFormPage` / `ProviderListPage` / `ConnectionPage` 里的 Snackbar 是附着于 Scaffold 的交互提示，语义不同，保持原样。
- 不做富 Toast（标题 / 图标 / 动作按钮）。Android 原生 Toast 够当前场景。
- 不暴露 `cancel()` / `clear()`。当前无需求，YAGNI。
- 不引入 Robolectric。见 §7。

## 3. API

```kotlin
// ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/ToastCenter.kt
object ToastCenter {
    fun show(
        context: Context,
        message: CharSequence,
        key: String = message.toString(),
        throttleMs: Long = 1500L,
        duration: Int = Toast.LENGTH_SHORT,
    )
}
```

## 4. 行为契约

1. **节流**：同 `key` 在 `throttleMs` 毫秒内重复调用被**静默丢弃**，不抛异常。
2. **单例显示**：任一次未被节流的 `show` 先 `cancel()` 掉 `ToastCenter` 持有的上一条 Toast，再创建并显示新 Toast。
3. **主线程安全**：内部使用 `Handler(Looper.getMainLooper()).post { ... }` 包裹所有 Toast 操作，任意线程调用均安全。
4. **context 防泄漏**：内部存 `context.applicationContext`，不持 Activity 引用。
5. **进程生命周期**：节流表与当前 Toast 引用随进程存在，App 被杀后自然清空；无需手动重置。

## 5. 内部结构

```kotlin
object ToastCenter {
    private val lock = Any()
    private val lastShownAt = HashMap<String, Long>()  // key -> clock() 时间戳
    private var currentToast: Toast? = null

    // ---- internal 测试桩点：生产路径使用默认值，测试路径替换 ----
    @Volatile internal var clock: () -> Long = { SystemClock.uptimeMillis() }
    @Volatile internal var mainExecutor: (Runnable) -> Unit =
        { Handler(Looper.getMainLooper()).post(it) }
    @Volatile internal var toastFactory: (Context, CharSequence, Int) -> Toast =
        { ctx, msg, dur -> Toast.makeText(ctx, msg, dur) }

    fun show(
        context: Context,
        message: CharSequence,
        key: String = message.toString(),
        throttleMs: Long = 1500L,
        duration: Int = Toast.LENGTH_SHORT,
    ) {
        val now = clock()
        synchronized(lock) {
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
}
```

要点：

- 私有 `lock = Any()` 保护节流表并发访问（`show` 可能被后台线程调用）；不用 `synchronized(this)` 以免 `object` 单例 monitor 被外部代码抢占。
- 三个 `@Volatile internal var` 字段 `clock` / `mainExecutor` / `toastFactory` 是**唯一的测试桩点**：生产路径即默认值，测试 setup 替换、teardown 还原；`@Volatile` 保证跨线程可见性。
- 节流表**不主动清理**：key 数量由业务文案决定，量级很小，生命周期随进程即可。
- 节流比较使用 `val last = lastShownAt[key]; if (last != null && now - last < throttleMs) return`——不能用 `?: 0L` 兜底，否则 `clock()` 返回值小于 `throttleMs` 时首次调用会被错误节流。

## 6. 调用点迁移

| 文件 | 删除 | 替换为 |
|---|---|---|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt:137` | `var alreadyInSessionToast by remember { mutableStateOf<Toast?>(null) }` | 无 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt:259-264` | `alreadyInSessionToast?.cancel(); alreadyInSessionToast = Toast.makeText(context, "已在目标会话", Toast.LENGTH_SHORT).also { it.show() }` | `ToastCenter.show(context, "已在目标会话")` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt:155` | `var newSessionToast by remember { mutableStateOf<Toast?>(null) }` | 无 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt:293-298` | `newSessionToast?.cancel(); newSessionToast = Toast.makeText(context, "Already in a new chat", Toast.LENGTH_SHORT).also { it.show() }` | `ToastCenter.show(context, "Already in a new chat")` |

两文件中若 `android.widget.Toast` 不再被其他代码引用，同步删除 `import`。

## 6.5 README 更新

| README | 改动 |
|---|---|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/README.md` | ① 目录结构加 `ToastCenter.kt`<br>② 新增 `### ToastCenter` 段（语义 + API + 使用示例）<br>③ 修改导航表加「弹一次性 Toast 提示（防重复 + 同时刻最多一条） → `ToastCenter.kt`」 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/README.md` | 修改导航表加「弹一次性 Toast 提示 → `common/ToastCenter.kt`」 |
| `ui/mobile-android/README.md` | §修改导航加「弹一次性 Toast 提示 → `ui/common/ToastCenter.kt`」 |

`common/README.md` 新增段落内容：

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

## 7. 测试

新增 `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/common/ToastCenterTest.kt`。

`Toast.makeText` 与 `Handler(mainLooper).post` 无法在纯 JVM 单测直接运行。通过 §5 的三个 internal 桩点绕开：

- `@Before`：
  - `ToastCenter.clock = { fakeNow }` — `fakeNow` 为可变 Long
  - `ToastCenter.mainExecutor = { it.run() }` — 同步执行 Runnable
  - `ToastCenter.toastFactory = { _, _, _ -> mockToast() }` — 返回 mock `Toast`，记录 `cancel()` 调用
- `@After`：保存原始三个 lambda 引用并在测试结束时赋回，保证跨测试类互不污染

测试用例：

- `first call at clock zero is not throttled`：fakeNow = 0 调一次，`toastFactory` 被调 1 次（锁死 `?: 0L` 兜底边界 bug 的回归）
- `same key within throttle window is dropped`：fakeNow = 0 调一次，fakeNow = 500 再调同 key，`toastFactory` 只被调 1 次
- `same key after throttle window is shown`：fakeNow = 0 / 1600 两次同 key，两次均通过
- `different keys pass independently`：同一 fakeNow 两次不同 key，`toastFactory` 被调 2 次
- `second show cancels previous toast`：两次 `show`（不同 key 避开节流），前一次返回的 mock Toast `cancel()` 被调一次

通过 `Context` 参数传入 `mock<Context>()`，`applicationContext` stub 返回自身即可，不触碰任何 Android 实际实现。

## 8. 风险与回滚

- **风险 1**：`Handler(Looper.getMainLooper())` 在极早期调用链（App onCreate 之前）无法工作——当前所有调用点都在用户点击交互之后，进程已完全启动，不会触发。
- **风险 2**：`currentToast` 单例跨进程？`object` 是单进程单例，Android 默认 App 单进程，无问题。
- **风险 3**：同时 2+ key 在显示窗口叠加时，后来的 cancel 前一个导致短促闪烁？这正是设计所要的行为——同时刻最多一条。
- **回滚**：删除 `ToastCenter.kt` 与 `ToastCenterTest.kt`，两个调用点恢复旧的 `remember<Toast?> + cancel` 样板，README 删除对应段落。影响面为 0（无下游依赖）。

## 9. 实施验收清单

- [ ] `ToastCenter.kt` 新建于 `ui/common/`，行数 ≤ 80
- [ ] 两处调用点迁移完毕，旧样板代码与冗余 `import android.widget.Toast` 移除
- [ ] `ToastCenterTest.kt` 四个用例全部通过
- [ ] 三个 README 同步更新
- [ ] 手动验证：
  - [ ] 审批横幅：快速连点指向当前 session 的通知，只看到一次"已在目标会话"
  - [ ] 新对话按钮：空白会话下快速连点 5+ 次，只看到一次"Already in a new chat"
  - [ ] 两种场景交替点击（不同 key），两条 Toast 不会互相排队——后一次直接替换前一次
