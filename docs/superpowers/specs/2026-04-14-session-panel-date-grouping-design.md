---
integrated_to: mobile/session-panel.md
integrated_at: 2026-04-23
---

# Session 侧栏按日期分组 + 折叠设计

- 日期：2026-04-14
- 范围：Android App `SessionPanel`
- 目标文件：`ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SessionPanel.kt`

## 背景

当前 `SessionPanel` 的历史会话区是扁平列表，每一条 `SessionItem` 下方都带一行 `YYYY-MM-DD` 日期，在会话多时显得冗余且难以快速定位时间段。参考 DeepSeek 侧栏：按时间桶分组，组头显示时间段，组内条目只显日期外的信息，观感更清爽。

在此基础上我们更进一步：历史会话按**年 → 月**两级折叠，近期使用平铺桶，支持会话级折叠状态记忆与 active session 自动展开。

## 目标

- 去掉每条 session 下方的日期行
- 历史会话按时间桶分组显示，桶头显示时间段
- 近期平铺 4 个桶：今天 / 昨天 / 7 天内 / 30 天内
- 超过 30 天的会话按 `年 → 月` 两级组织，年、月均独立可折叠
- 每个 session 只归属一个桶，不重复
- 保留删除按钮
- 折叠状态在侧栏关闭/打开间保留（进程重启后重置为默认）
- active session 所在组自动展开（首次进入或切换 active 时）

## 非目标（YAGNI）

- 不加 session 计数徽标
- 不加多选/批量操作
- 不加搜索
- 不持久化折叠状态到 DataStore

---

## 层级与默认折叠

```
今天                    [展开]
昨天                    [展开]
7天内                   [展开]
30天内                  [展开]
▾ 2026年                [当年默认展开]
   ▸ 2026年4月           [月份默认全折叠]
   ▸ 2026年3月
   ▸ 2026年2月
▸ 2025年                [往年默认折叠]
   (展开后)
   ▸ 2025年12月          [月份默认全折叠]
   ▸ 2025年11月
```

理由：近期 4 个平铺桶已覆盖 30 天内所有会话；年/月树纯粹是历史考古入口，月份全折叠最干净。

---

## 数据建模

新文件：`ui/chat/SessionGrouping.kt`（纯逻辑，便于单测）。

```kotlin
sealed class SessionBucket {
    abstract val key: String
    abstract val label: String
    abstract val sessions: List<Session>

    data class Recent(
        override val key: String,          // "today" / "yesterday" / "within7" / "within30"
        override val label: String,
        override val sessions: List<Session>,
    ) : SessionBucket()

    data class Month(
        val year: Int,
        val month: Int,                    // 1..12
        override val sessions: List<Session>,
    ) : SessionBucket() {
        override val key = "m-$year-$month"
        override val label = "${year}年${month}月"
    }

    data class Year(
        val year: Int,
        val months: List<Month>,
    ) : SessionBucket() {
        override val key = "y-$year"
        override val label = "${year}年"
        override val sessions: List<Session> get() = months.flatMap { it.sessions }
    }
}

data class GroupedSessions(
    val recent: List<SessionBucket.Recent>,
    val years: List<SessionBucket.Year>,
)
```

### 分桶函数

```kotlin
fun groupSessions(
    sessions: List<Session>,
    now: LocalDate = LocalDate.now(),
): GroupedSessions
```

规则：

1. **分桶**按日期粒度：取 `session.lastActivityAt` 前 10 位 `YYYY-MM-DD` 转 `LocalDate`。
2. 按优先级归桶，一个 session 只进一个桶：
   - 日期 == now → `today`
   - 日期 == now - 1 → `yesterday`
   - now - 7 ≤ 日期 < now - 1 → `within7`
   - now - 30 ≤ 日期 < now - 7 → `within30`
   - 日期 < now - 30 → 按 `(year, month)` 进入对应 `Month`，`Month` 再聚合到 `Year`
3. `lastActivityAt` 为 null 或解析失败 → 兜底归到 `today`，避免丢失。
4. **组内排序**使用完整 `lastActivityAt`（ISO 字符串字典序 == 时间序，天然精确到秒），desc；null 值排在最后。
5. 月份在年内按 `month desc` 排；年份按 `year desc` 排。
6. Recent 桶按固定顺序输出：today / yesterday / within7 / within30；空桶不输出。
7. Year/Month 空的也不输出。

### 默认折叠状态

```kotlin
fun defaultExpanded(grouped: GroupedSessions, now: LocalDate): Map<String, Boolean> {
    val map = mutableMapOf<String, Boolean>()
    grouped.recent.forEach { map[it.key] = true }
    grouped.years.forEach { year ->
        map[year.key] = (year.year == now.year)
        year.months.forEach { map[it.key] = false }
    }
    return map
}
```

---

## UI 结构

### 组件拆分

保持 `SessionPanel` 对外签名不变。内部新增：

- `GroupHeader(label, expanded, level, onToggle)` — 统一的可折叠组头，带 chevron；`level=0` 为顶层（Recent/Year），`level=1` 为月份，左内缩 16.dp。
- 现有 `SessionItem` 改造：删掉 `ui/chat/SessionPanel.kt` 当前 L273-L279 的日期 `Text`，其余保留（title + 删除按钮 + active 背景色）。

### 折叠状态

```kotlin
val grouped = remember(sessions) { groupSessions(sessions) }
val defaults = remember(grouped) { defaultExpanded(grouped, LocalDate.now()) }
val expanded = rememberSaveable(
    grouped,
    saver = mapSaver(
        save = { it.toMap() },
        restore = { mutableStateMapOf<String, Boolean>().apply { putAll(it.mapValues { e -> e.value as Boolean }) } },
    ),
) { mutableStateMapOf<String, Boolean>().apply { putAll(defaults) } }
```

`rememberSaveable` 保证侧栏关闭再打开状态保留；进程重启时 Compose 的 saver 失效，回到默认（符合设计意图）。

### Active 自动展开

```kotlin
LaunchedEffect(activeSessionId, grouped) {
    if (activeSessionId == null) return@LaunchedEffect
    // 仅处理 year/month 路径；Recent 默认就是展开状态
    grouped.years.forEach { year ->
        year.months.forEach { month ->
            if (month.sessions.any { it.id == activeSessionId }) {
                expanded[year.key] = true
                expanded[month.key] = true
            }
        }
    }
}
```

`key = activeSessionId` 保证切换 active 时才重新触发；不会在用户手动折叠后持续覆盖状态（一次性副作用）。

### LazyColumn 渲染

```
LazyColumn {
  for bucket in grouped.recent:
    item(key="h-${bucket.key}") { GroupHeader(bucket.label, expanded[bucket.key], level=0) }
    if expanded[bucket.key] == true:
      items(bucket.sessions, key={ it.id }) { SessionItem(...) }

  for year in grouped.years:
    item(key="h-${year.key}") { GroupHeader(year.label, expanded[year.key], level=0) }
    if expanded[year.key] == true:
      for month in year.months:
        item(key="h-${month.key}") { GroupHeader(month.label, expanded[month.key], level=1) }
        if expanded[month.key] == true:
          items(month.sessions, key={ it.id }) { SessionItem(...) }
}
```

### 视觉细节

- `GroupHeader`：
  - chevron 图标：`KeyboardArrowDown`（展开）/ `KeyboardArrowRight`（折叠），12sp，`onSurfaceVariant`
  - 文字：`labelSmall` + `FontWeight.Medium`，`onSurfaceVariant`
  - 整行 clickable 切换折叠
  - padding：`horizontal = 4.dp + level*16.dp, vertical = 8.dp`
  - 不显示计数（保持 DeepSeek 风格克制）
- `SessionItem`：删除日期行后行高自然降低，更紧凑。

---

## 测试方案

新增 `app/src/test/java/com/sebastian/android/ui/chat/SessionGroupingTest.kt`，覆盖：

1. 今天边界：`now - 0` 归 today
2. 昨天边界：`now - 1` 归 yesterday
3. 7 天内：`now - 2`、`now - 7` 归 within7；`now - 1` 不归（已归 yesterday）
4. 30 天内：`now - 8`、`now - 30` 归 within30；`now - 7` 不归 within30
5. 31 天前：`now - 31` 归 year/month
6. 跨年：`2025-12-31` 归 `Year(2025).Month(12)`
7. `lastActivityAt` 为 null → 归 today
8. 组内排序 desc（同一天内不同秒的 session 也能正确排序）；月份 desc；年份 desc
9. 空列表 → `GroupedSessions(emptyList(), emptyList())`
10. `defaultExpanded`：所有 Recent = true；当年 Year = true；往年 Year = false；所有 Month = false

UI 层不强制单测（Compose UI 测试成本高、收益低，手动验证即可）。

---

## 改动清单

### 新增

- `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SessionGrouping.kt`
- `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/SessionGroupingTest.kt`

### 修改

- `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SessionPanel.kt`
  - LazyColumn 改为分组渲染
  - 新增 `GroupHeader` 私有 composable
  - `SessionItem` 去掉日期行
  - 新增 `rememberSaveable` 折叠 map 与 `LaunchedEffect` active 展开逻辑

对外签名不变，零破坏性改动。

---

## 验证

1. `./gradlew :app:lintDebug` 通过
2. `./gradlew :app:testDebugUnitTest --tests "*SessionGroupingTest*"` 全绿
3. 手动在模拟器验证：
   - 4 个 Recent 桶展开态下正确分组
   - 当年默认展开、月份默认折叠、往年默认折叠
   - 点击 chevron 切换折叠生效
   - 侧栏关闭再打开，折叠状态保留
   - 选中往年某个 session 后再打开侧栏，对应年+月自动展开
   - 删除按钮仍可用
