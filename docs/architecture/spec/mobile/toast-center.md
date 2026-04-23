---
version: "1.0"
last_updated: 2026-04-23
status: implemented
---

# ToastCenter 公共组件

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景与目标

Android App 内多处一次性 Toast 提示（如"已在目标会话"、"Already in a new chat"），原先各自维护 `var xxxToast by remember { mutableStateOf<Toast?>(null) }`，样板重复且只解决了「不排队」问题——用户连点仍会看到 Toast 不停闪烁重弹。

抽取公共 `ToastCenter`，一次性解决两个问题：

1. **时间窗口节流**：同 `key` 在 `throttleMs` 内重复调用被丢弃
2. **同时刻最多一条**：进程内新 Toast 先 cancel 旧的再显示

---

## 2. 非目标

- 不替换 Snackbar。`ProviderFormPage` / `ProviderListPage` / `ConnectionPage` 里的 Snackbar 是附着于 Scaffold 的交互提示，语义不同。
- 不做富 Toast（标题 / 图标 / 动作按钮）。Android 原生 Toast 够当前场景。
- 不暴露 `cancel()` / `clear()`。YAGNI。
- 不引入 Robolectric。

---

## 3. API

```kotlin
// ui/mobile-android/.../ui/common/ToastCenter.kt
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

---

## 4. 行为契约

1. **节流**：同 `key` 在 `throttleMs` 毫秒内重复调用被**静默丢弃**，不抛异常。
2. **单例显示**：任一次未被节流的 `show` 先 `cancel()` 掉 `ToastCenter` 持有的上一条 Toast，再创建并显示新 Toast。
3. **主线程安全**：内部使用 `mainExecutor`（默认 `Handler(Looper.getMainLooper()).post`）包裹所有 Toast 操作，任意线程调用均安全。
4. **context 防泄漏**：内部存 `context.applicationContext`，不持 Activity 引用。
5. **进程生命周期**：节流表与当前 Toast 引用随进程存在，App 被杀后自然清空；无需手动重置。

---

## 5. 内部结构

```kotlin
object ToastCenter {
    private val lock = Any()
    private val lastShownAt = HashMap<String, Long>()  // key -> clock() 时间戳
    private var currentToast: Toast? = null

    @Volatile @VisibleForTesting internal var clock: () -> Long = { SystemClock.uptimeMillis() }
    @Volatile @VisibleForTesting internal var mainExecutor: (Runnable) -> Unit =
        { Handler(Looper.getMainLooper()).post(it) }
    @Volatile @VisibleForTesting internal var toastFactory: (Context, CharSequence, Int) -> Toast =
        { ctx, msg, dur -> Toast.makeText(ctx, msg, dur) }

    @VisibleForTesting
    internal fun resetForTest() { lastShownAt.clear(); currentToast = null }

    fun show(...) { /* 节流检查 → applicationContext → mainExecutor → cancel旧/show新 */ }
}
```

> **实现增强**：代码包含 `resetForTest()` 方法（spec 原文未提及），用于测试清理 `lastShownAt` 和 `currentToast`。三个 internal 桩点均标记 `@Volatile`，保证跨线程可见性。

要点：

- `lock = Any()` 保护节流表并发访问；不用 `synchronized(this)` 以免单例 monitor 被外部抢占。
- 三个 `@Volatile internal var` 字段 `clock` / `mainExecutor` / `toastFactory` 是**唯一的测试桩点**：生产路径用默认值，测试 setup 替换、teardown 还原。
- 节流比较使用 `val last = lastShownAt[key]; if (last != null && now - last < throttleMs) return`——不能用 `?: 0L` 兜底，否则 `clock()` 返回值小于 `throttleMs` 时首次调用会被错误节流。

---

## 6. 调用点

| 文件 | 调用 |
|---|---|
| `MainActivity.kt` | `ToastCenter.show(context, "已在目标会话")` — 审批横幅点击时已在目标会话 |
| `ChatScreen.kt` | `ToastCenter.show(context, "Already in a new chat")` — 空白新对话时点"新对话" |
| `ChatScreen.kt` | `ToastCenter.show(toastContext, message, key = "pending_timeout", throttleMs = 10_000L)` — ViewModel toastEvents 消费 |

> **实现增强**：ChatScreen 中额外增加了 `pending_timeout` key 的调用（用于 PENDING 超时提示），spec 原文只列了前两处。

---

## 7. 测试

`ui/mobile-android/.../ui/common/ToastCenterTest.kt`，5 个用例：

| # | 用例 | 覆盖点 |
|---|---|---|
| 1 | `first call at clock zero is not throttled` | 回归：防止 `fakeNow = 0` 的首次调用被误节流 |
| 2 | `same key within throttle window is dropped` | 同 key 节流 |
| 3 | `same key after throttle window is shown` | 超出窗口后正常 |
| 4 | `different keys pass independently` | 不同 key 独立 |
| 5 | `second show cancels previous toast` | 新 Toast cancel 旧 |

---

## 8. 不在本 spec 范围内

- Snackbar 交互（保持 Scaffold 附着）
- 富 Toast / 自定义 Toast View
- Toast 队列管理（当前只需同时刻一条）

---

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
