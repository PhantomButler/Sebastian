# Session 侧栏按日期分组 + 折叠 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Android `SessionPanel` 历史会话从扁平列表改为按时间分组（今天/昨天/7天内/30天内 + 年→月折叠），去掉每条的日期行，保留删除按钮，支持会话级折叠记忆与 active 自动展开。

**Architecture:** 新增纯逻辑文件 `SessionGrouping.kt` 负责分桶与默认折叠态，独立可单测；改造 `SessionPanel.kt` 的 LazyColumn 渲染为分组结构，折叠状态用 `rememberSaveable` 的 `mutableStateMapOf<String, Boolean>`；`LaunchedEffect(activeSessionId)` 处理 active session 自动展开。

**Tech Stack:** Kotlin, Jetpack Compose Material3, JUnit 4, `java.time.LocalDate`

**参考 Spec:** `docs/superpowers/specs/2026-04-14-session-panel-date-grouping-design.md`

---

## 文件结构

### 新增
- `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SessionGrouping.kt`
  - `SessionBucket` sealed class（Recent / Month / Year）
  - `GroupedSessions` data class
  - `groupSessions(sessions, now): GroupedSessions`
  - `defaultExpanded(grouped, now): Map<String, Boolean>`

- `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/SessionGroupingTest.kt`
  - 覆盖分桶边界、排序、null 兜底、默认折叠态

### 修改
- `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SessionPanel.kt`
  - LazyColumn 渲染改为分组结构
  - 新增私有 `GroupHeader` composable
  - `SessionItem` 删除日期行（L272-L279）
  - 新增折叠状态 map + active 自动展开 `LaunchedEffect`

---

## Task 1：`SessionGrouping.kt` 数据模型与分桶函数（TDD）

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SessionGrouping.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/SessionGroupingTest.kt`

- [ ] **Step 1.1：写 `SessionGroupingTest.kt` 的失败测试（分桶边界 + 排序 + null 兜底）**

```kotlin
package com.sebastian.android.ui.chat

import com.sebastian.android.data.model.Session
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class SessionGroupingTest {

    private val now: LocalDate = LocalDate.of(2026, 4, 14)

    private fun s(id: String, date: String?): Session =
        Session(id = id, title = id, agentType = "chat", lastActivityAt = date)

    @Test
    fun `today bucket covers now`() {
        val grouped = groupSessions(listOf(s("a", "2026-04-14T10:00:00")), now)
        assertEquals(1, grouped.recent.size)
        assertEquals("today", grouped.recent[0].key)
        assertEquals(listOf("a"), grouped.recent[0].sessions.map { it.id })
    }

    @Test
    fun `yesterday bucket covers now minus 1`() {
        val grouped = groupSessions(listOf(s("a", "2026-04-13T23:59:00")), now)
        assertEquals("yesterday", grouped.recent[0].key)
    }

    @Test
    fun `within7 covers 2 to 7 days ago exclusive of yesterday`() {
        val grouped = groupSessions(
            listOf(s("a", "2026-04-12T00:00:00"), s("b", "2026-04-07T00:00:00")),
            now,
        )
        assertEquals(1, grouped.recent.size)
        assertEquals("within7", grouped.recent[0].key)
        assertEquals(listOf("a", "b"), grouped.recent[0].sessions.map { it.id })
    }

    @Test
    fun `within30 covers 8 to 30 days ago`() {
        val grouped = groupSessions(
            listOf(s("a", "2026-04-06T00:00:00"), s("b", "2026-03-15T00:00:00")),
            now,
        )
        assertEquals("within30", grouped.recent[0].key)
        assertEquals(listOf("a", "b"), grouped.recent[0].sessions.map { it.id })
    }

    @Test
    fun `older than 30 days goes into year and month`() {
        val grouped = groupSessions(
            listOf(s("a", "2026-03-10T00:00:00"), s("b", "2025-12-31T23:59:00")),
            now,
        )
        assertTrue(grouped.recent.isEmpty())
        assertEquals(2, grouped.years.size)
        // years desc
        assertEquals(2026, grouped.years[0].year)
        assertEquals(2025, grouped.years[1].year)
        assertEquals(3, grouped.years[0].months[0].month)
        assertEquals(12, grouped.years[1].months[0].month)
    }

    @Test
    fun `null lastActivityAt falls back to today`() {
        val grouped = groupSessions(listOf(s("a", null)), now)
        assertEquals("today", grouped.recent[0].key)
    }

    @Test
    fun `within-bucket sort is lastActivityAt desc with second precision`() {
        val grouped = groupSessions(
            listOf(
                s("early", "2026-04-14T08:00:30"),
                s("late", "2026-04-14T08:00:45"),
                s("mid", "2026-04-14T08:00:40"),
            ),
            now,
        )
        assertEquals(listOf("late", "mid", "early"), grouped.recent[0].sessions.map { it.id })
    }

    @Test
    fun `months within a year are desc`() {
        val grouped = groupSessions(
            listOf(
                s("a", "2026-02-01T00:00:00"),
                s("b", "2026-03-01T00:00:00"),
                s("c", "2026-01-01T00:00:00"),
            ),
            now,
        )
        val months = grouped.years[0].months.map { it.month }
        assertEquals(listOf(3, 2, 1), months)
    }

    @Test
    fun `empty input produces empty grouped`() {
        val grouped = groupSessions(emptyList(), now)
        assertTrue(grouped.recent.isEmpty())
        assertTrue(grouped.years.isEmpty())
    }

    @Test
    fun `recent bucket order is today yesterday within7 within30`() {
        val grouped = groupSessions(
            listOf(
                s("w30", "2026-03-20T00:00:00"),
                s("today", "2026-04-14T00:00:00"),
                s("w7", "2026-04-10T00:00:00"),
                s("y", "2026-04-13T00:00:00"),
            ),
            now,
        )
        assertEquals(listOf("today", "yesterday", "within7", "within30"), grouped.recent.map { it.key })
    }

    @Test
    fun `defaultExpanded expands recent and current year only`() {
        val grouped = groupSessions(
            listOf(
                s("now", "2026-04-14T00:00:00"),
                s("cur-year", "2026-02-01T00:00:00"),
                s("old", "2025-06-01T00:00:00"),
            ),
            now,
        )
        val defaults = defaultExpanded(grouped, now)
        assertEquals(true, defaults["today"])
        assertEquals(true, defaults["y-2026"])
        assertEquals(false, defaults["y-2025"])
        assertEquals(false, defaults["m-2026-2"])
        assertEquals(false, defaults["m-2025-6"])
    }
}
```

- [ ] **Step 1.2：运行测试确认失败**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.SessionGroupingTest"`
Expected: FAIL — `unresolved reference: groupSessions` / `SessionGrouping` 相关符号。

- [ ] **Step 1.3：创建 `SessionGrouping.kt` 的最小实现**

```kotlin
package com.sebastian.android.ui.chat

import com.sebastian.android.data.model.Session
import java.time.LocalDate
import java.time.format.DateTimeParseException

sealed class SessionBucket {
    abstract val key: String
    abstract val label: String
    abstract val sessions: List<Session>

    data class Recent(
        override val key: String,
        override val label: String,
        override val sessions: List<Session>,
    ) : SessionBucket()

    data class Month(
        val year: Int,
        val month: Int,
        override val sessions: List<Session>,
    ) : SessionBucket() {
        override val key: String = "m-$year-$month"
        override val label: String = "${year}年${month}月"
    }

    data class Year(
        val year: Int,
        val months: List<Month>,
    ) : SessionBucket() {
        override val key: String = "y-$year"
        override val label: String = "${year}年"
        override val sessions: List<Session>
            get() = months.flatMap { it.sessions }
    }
}

data class GroupedSessions(
    val recent: List<SessionBucket.Recent>,
    val years: List<SessionBucket.Year>,
)

private fun parseDate(raw: String?): LocalDate? {
    if (raw == null || raw.length < 10) return null
    return try {
        LocalDate.parse(raw.substring(0, 10))
    } catch (_: DateTimeParseException) {
        null
    }
}

/** ISO 字符串字典序 == 时间序；null 排最后。desc。 */
private val sessionTimeDesc = Comparator<Session> { a, b ->
    val av = a.lastActivityAt
    val bv = b.lastActivityAt
    when {
        av == null && bv == null -> 0
        av == null -> 1
        bv == null -> -1
        else -> bv.compareTo(av)
    }
}

fun groupSessions(
    sessions: List<Session>,
    now: LocalDate = LocalDate.now(),
): GroupedSessions {
    val today = mutableListOf<Session>()
    val yesterday = mutableListOf<Session>()
    val within7 = mutableListOf<Session>()
    val within30 = mutableListOf<Session>()
    // (year, month) -> sessions
    val monthMap = linkedMapOf<Pair<Int, Int>, MutableList<Session>>()

    for (session in sessions) {
        val date = parseDate(session.lastActivityAt)
        if (date == null) {
            today += session
            continue
        }
        val daysAgo = java.time.temporal.ChronoUnit.DAYS.between(date, now)
        when {
            daysAgo <= 0L -> today += session            // 今天或未来时间戳都归今天
            daysAgo == 1L -> yesterday += session
            daysAgo in 2L..7L -> within7 += session
            daysAgo in 8L..30L -> within30 += session
            else -> {
                val key = date.year to date.monthValue
                monthMap.getOrPut(key) { mutableListOf() } += session
            }
        }
    }

    val recent = buildList {
        if (today.isNotEmpty()) {
            add(SessionBucket.Recent("today", "今天", today.sortedWith(sessionTimeDesc)))
        }
        if (yesterday.isNotEmpty()) {
            add(SessionBucket.Recent("yesterday", "昨天", yesterday.sortedWith(sessionTimeDesc)))
        }
        if (within7.isNotEmpty()) {
            add(SessionBucket.Recent("within7", "7天内", within7.sortedWith(sessionTimeDesc)))
        }
        if (within30.isNotEmpty()) {
            add(SessionBucket.Recent("within30", "30天内", within30.sortedWith(sessionTimeDesc)))
        }
    }

    // 按年聚合月份：year desc，month desc
    val byYear = monthMap.entries
        .groupBy { it.key.first }
        .toSortedMap(compareByDescending { it })
    val years = byYear.map { (year, entries) ->
        val months = entries
            .sortedByDescending { it.key.second }
            .map { (yk, list) ->
                SessionBucket.Month(
                    year = yk.first,
                    month = yk.second,
                    sessions = list.sortedWith(sessionTimeDesc),
                )
            }
        SessionBucket.Year(year = year, months = months)
    }

    return GroupedSessions(recent = recent, years = years)
}

fun defaultExpanded(
    grouped: GroupedSessions,
    now: LocalDate = LocalDate.now(),
): Map<String, Boolean> {
    val map = linkedMapOf<String, Boolean>()
    grouped.recent.forEach { map[it.key] = true }
    grouped.years.forEach { year ->
        map[year.key] = (year.year == now.year)
        year.months.forEach { map[it.key] = false }
    }
    return map
}
```

- [ ] **Step 1.4：运行测试确认通过**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.SessionGroupingTest"`
Expected: PASS（10 个测试全绿）

- [ ] **Step 1.5：提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SessionGrouping.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/SessionGroupingTest.kt
git commit -m "$(cat <<'EOF'
feat(android): 新增 session 分桶纯逻辑 SessionGrouping

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2：改造 `SessionPanel.kt` 使用分组渲染

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SessionPanel.kt`

### 逐步改造 `SessionPanel.kt`

- [ ] **Step 2.1：删除 `SessionItem` 中的日期行**

在 `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SessionPanel.kt` 找到 `SessionItem` 内 `session.lastActivityAt?.let { dateStr -> ... }` 这一段（当前 L272-L279），整段删除。保留 title `Text`、删除按钮与外层 Surface/Row。

删除后 `Column { ... }` 内只剩一个 title `Text`：

```kotlin
Column(
    modifier = Modifier
        .weight(1f)
        .clickable(onClick = onClick)
        .padding(horizontal = 8.dp, vertical = 10.dp),
) {
    Text(
        text = session.title.ifBlank { "新对话" },
        style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Medium),
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        color = MaterialTheme.colorScheme.onSurface,
    )
}
```

- [ ] **Step 2.2：在 `SessionPanel` 文件里新增 `GroupHeader` 私有 composable**

把下列函数加到文件底部（与其他 private composable 同级）：

```kotlin
@Composable
private fun GroupHeader(
    label: String,
    expanded: Boolean,
    level: Int,
    onToggle: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onToggle)
            .padding(
                start = (4 + level * 16).dp,
                end = 4.dp,
                top = 8.dp,
                bottom = 8.dp,
            ),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = if (expanded) {
                androidx.compose.material.icons.Icons.Default.KeyboardArrowDown
            } else {
                androidx.compose.material.icons.Icons.Default.KeyboardArrowRight
            },
            contentDescription = if (expanded) "折叠" else "展开",
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(14.dp),
        )
        Spacer(Modifier.width(4.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.Medium),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
```

同时在文件顶部 imports 里补：

```kotlin
import androidx.compose.foundation.layout.Spacer
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.snapshots.SnapshotStateMap
import java.time.LocalDate
```

（注意：`Spacer` / `width` 等若已存在就不重复添加；`mutableStateMapOf` 与 `rememberSaveable` 是本次新增）

- [ ] **Step 2.3：替换 `SessionPanel` 的历史区 LazyColumn 渲染**

把当前 `SessionPanel` 中「History section」整段（`Column(modifier = Modifier.weight(1f)...)` 那整个块）替换为以下实现。

先在 `SessionPanel` 函数开头（`val isDark = ...` 之后，`Box` 之前）加：

```kotlin
val grouped = remember(sessions) { groupSessions(sessions) }
val defaults = remember(grouped) { defaultExpanded(grouped, LocalDate.now()) }
val expanded: SnapshotStateMap<String, Boolean> = rememberSaveable(
    grouped,
    saver = androidx.compose.runtime.saveable.Saver(
        save = { it.toMap() },
        restore = { restored ->
            mutableStateMapOf<String, Boolean>().apply {
                @Suppress("UNCHECKED_CAST")
                putAll(restored as Map<String, Boolean>)
            }
        },
    ),
) {
    mutableStateMapOf<String, Boolean>().apply { putAll(defaults) }
}

// grouped 变化时补齐新 key 的默认值（不覆盖用户已有选择）
LaunchedEffect(grouped) {
    defaults.forEach { (k, v) -> if (!expanded.containsKey(k)) expanded[k] = v }
}

// activeSessionId 变化时，展开 active 所在年+月
LaunchedEffect(activeSessionId, grouped) {
    if (activeSessionId == null) return@LaunchedEffect
    for (year in grouped.years) {
        for (month in year.months) {
            if (month.sessions.any { it.id == activeSessionId }) {
                expanded[year.key] = true
                expanded[month.key] = true
                return@LaunchedEffect
            }
        }
    }
}
```

然后把历史区 `Column { Text("历史对话"...) ; LazyColumn { items(sessions)... } }` 替换为：

```kotlin
Column(
    modifier = Modifier
        .weight(1f)
        .padding(horizontal = 12.dp),
) {
    Text(
        text = "历史对话",
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(start = 4.dp, top = 12.dp, bottom = 4.dp),
    )
    LazyColumn(modifier = Modifier.weight(1f)) {
        // Recent 平铺桶
        grouped.recent.forEach { bucket ->
            val isOpen = expanded[bucket.key] ?: true
            item(key = "h-${bucket.key}") {
                GroupHeader(
                    label = bucket.label,
                    expanded = isOpen,
                    level = 0,
                    onToggle = { expanded[bucket.key] = !isOpen },
                )
            }
            if (isOpen) {
                items(bucket.sessions, key = { it.id }) { session ->
                    SessionItem(
                        session = session,
                        isActive = session.id == activeSessionId,
                        onClick = { onSessionClick(session) },
                        onDelete = { onDeleteSession(session) },
                    )
                }
            }
        }
        // 年 / 月
        grouped.years.forEach { year ->
            val yearOpen = expanded[year.key] ?: false
            item(key = "h-${year.key}") {
                GroupHeader(
                    label = year.label,
                    expanded = yearOpen,
                    level = 0,
                    onToggle = { expanded[year.key] = !yearOpen },
                )
            }
            if (yearOpen) {
                year.months.forEach { month ->
                    val monthOpen = expanded[month.key] ?: false
                    item(key = "h-${month.key}") {
                        GroupHeader(
                            label = month.label,
                            expanded = monthOpen,
                            level = 1,
                            onToggle = { expanded[month.key] = !monthOpen },
                        )
                    }
                    if (monthOpen) {
                        items(month.sessions, key = { it.id }) { session ->
                            SessionItem(
                                session = session,
                                isActive = session.id == activeSessionId,
                                onClick = { onSessionClick(session) },
                                onDelete = { onDeleteSession(session) },
                            )
                        }
                    }
                }
            }
        }
    }
}
```

- [ ] **Step 2.4：构建 + lint 通过**

Run:
```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin
```
Expected: BUILD SUCCESSFUL，无 unresolved reference。

Run:
```bash
cd ui/mobile-android && ./gradlew :app:lintDebug
```
Expected: BUILD SUCCESSFUL（警告可以有，error 为 0）。

- [ ] **Step 2.5：现有单元测试不回归**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest`
Expected: 全部 PASS，包括 Task 1 新增的 `SessionGroupingTest`。

- [ ] **Step 2.6：手动在模拟器验证**

启动模拟器并安装：
```bash
cd ui/mobile-android && npx expo run:android 2>/dev/null || ./gradlew :app:installDebug
```

（如果 `expo` 不在该项目适用——本仓库为 Android 原生——直接用 gradle）：
```bash
cd ui/mobile-android && ./gradlew :app:installDebug
~/Library/Android/sdk/platform-tools/adb shell am start -n com.sebastian.android/.MainActivity
```

在 App 内打开侧栏，逐一验证：
- [ ] 近期 4 个桶（今天/昨天/7天内/30天内）默认展开，chevron 向下
- [ ] 当年（2026年）默认展开；展开后 2026年4月/3月... 月份默认折叠，chevron 向右
- [ ] 往年（如 2025年）默认折叠
- [ ] 点击任一 chevron 能切换折叠
- [ ] 每条 session 下面不再显示日期
- [ ] 删除按钮仍可用
- [ ] 关掉侧栏再打开，折叠状态保留
- [ ] 选中往年某个 session 后再打开侧栏，对应年+月自动展开

- [ ] **Step 2.7：提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SessionPanel.kt
git commit -m "$(cat <<'EOF'
feat(android): SessionPanel 按日期分组 + 折叠展示

- 历史会话按 今天/昨天/7天内/30天内 + 年→月 两级折叠
- 每条 session 不再显示日期行
- rememberSaveable 保留会话级折叠状态
- active session 所在年/月自动展开

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3：更新模块 README 导航

**Files:**
- Modify: `ui/mobile-android/README.md`（若有「修改导航」或聊天 UI 描述段落）

- [ ] **Step 3.1：检查 README 是否需要同步**

Run: `grep -n "SessionPanel\|session 侧栏\|聊天列表" ui/mobile-android/README.md`
- 若命中相关段落 → Step 3.2 更新
- 若未命中 → 跳过 Task 3

- [ ] **Step 3.2：补一行说明分桶逻辑位置**

在 README 中聊天 UI / 侧栏相关章节追加：

```markdown
- 会话侧栏分桶逻辑：`app/src/main/java/com/sebastian/android/ui/chat/SessionGrouping.kt`（纯函数，有单测）
```

- [ ] **Step 3.3：提交**

```bash
git add ui/mobile-android/README.md
git commit -m "$(cat <<'EOF'
docs(android): README 补充 session 分桶逻辑位置

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## 最终验证

- [ ] `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest` 全绿
- [ ] `cd ui/mobile-android && ./gradlew :app:lintDebug` 无 error
- [ ] 模拟器上 Step 2.6 的 8 项手动验证全部通过
- [ ] `git log --oneline -4` 能看到 3 个原子 commit（Task 3 若跳过则 2 个）
