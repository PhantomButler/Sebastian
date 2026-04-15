# Android 主题颜色补全 & SebastianSwitch 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全 Material3 缺失颜色 token 消除紫色 fallback，修掉 4 处硬编码颜色，新建苹果绿 SebastianSwitch 公共组件并替换 3 处用法。

**Architecture:** 只改 `Color.kt` 和 `SebastianTheme.kt` 两个主题文件补全 9 个 M3 token，所有业务页面自动生效无需修改。新建 `SebastianSwitch.kt` 封装苹果绿开关，替换现有 3 处 `Switch` 用法。逐步修掉 ThinkButton / GlobalApprovalBanner 的硬编码颜色。

**Tech Stack:** Kotlin、Jetpack Compose、Material3（`lightColorScheme` / `darkColorScheme` / `SwitchDefaults`）

---

## 文件清单

| 操作 | 文件路径 |
|---|---|
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/theme/Color.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/theme/SebastianTheme.kt` |
| 新建 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/SebastianSwitch.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AppearancePage.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/DebugLoggingPage.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderFormPage.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/ThinkButton.kt` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/GlobalApprovalBanner.kt` |

---

## Task 1：Color.kt 追加颜色常量

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/theme/Color.kt`

- [ ] **Step 1：在 Color.kt 末尾追加 20 个颜色常量**

在文件现有内容（`UserBubbleBorderDark` 之后）追加：

```kotlin
// ── 补全 M3 token（日间）──────────────────────────────────────────────────────
val SurfaceContainerLight = Color(0xFFF1F3F4)       // 卡片背景
val SurfaceContainerHighestLight = Color(0xFFE8EAED) // 输入框容器
val SurfaceContainerLowLight = Color(0xFFF8F9FA)     // 低层级容器
val PrimaryContainerLight = Color(0xFFD3E3FD)        // 蓝色浅容器
val ErrorLight = Color(0xFFB00020)                   // 错误红
val OnErrorLight = Color(0xFFFFFFFF)                 // 错误上文字
val ErrorContainerLight = Color(0xFFFFDAD6)          // 错误浅容器
val OnErrorContainerLight = Color(0xFF410002)        // 错误容器上文字
val OutlineVariantLight = Color(0xFFC7C7CC)          // 分割线

// ── 补全 M3 token（夜间）──────────────────────────────────────────────────────
val SurfaceContainerDark = Color(0xFF292B2D)
val SurfaceContainerHighestDark = Color(0xFF36393B)
val SurfaceContainerLowDark = Color(0xFF252729)
val PrimaryContainerDark = Color(0xFF0A3266)
val ErrorDark = Color(0xFFCF6679)
val OnErrorDark = Color(0xFF690005)
val ErrorContainerDark = Color(0xFF93000A)
val OnErrorContainerDark = Color(0xFFFFDAD6)
val OutlineVariantDark = Color(0xFF3C3F41)

// ── SebastianSwitch 苹果绿 ───────────────────────────────────────────────────
val SwitchCheckedLight = Color(0xFF34C759)  // 日间苹果绿
val SwitchCheckedDark = Color(0xFF30D158)   // 夜间苹果绿（更亮）
```

- [ ] **Step 2：编译验证**

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew compileDebugKotlin 2>&1 | tail -5
```

期望输出包含 `BUILD SUCCESSFUL`，无 error。

- [ ] **Step 3：提交**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/theme/Color.kt
git commit -m "style(android): 补全 M3 颜色 token 常量及苹果绿开关色

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2：SebastianTheme.kt 补全 token 覆盖

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/theme/SebastianTheme.kt`

- [ ] **Step 1：将 LightColors 替换为包含全部 token 的版本**

将文件中 `private val LightColors = lightColorScheme(` 整块替换为：

```kotlin
private val LightColors = lightColorScheme(
    primary = PrimaryLight,
    onPrimary = OnPrimaryLight,
    surface = SurfaceLight,
    onSurface = OnSurfaceLight,
    background = BackgroundLight,
    surfaceVariant = SurfaceVariantLight,
    onSurfaceVariant = OnSurfaceVariantLight,
    surfaceContainer = SurfaceContainerLight,
    surfaceContainerHighest = SurfaceContainerHighestLight,
    surfaceContainerLow = SurfaceContainerLowLight,
    primaryContainer = PrimaryContainerLight,
    error = ErrorLight,
    onError = OnErrorLight,
    errorContainer = ErrorContainerLight,
    onErrorContainer = OnErrorContainerLight,
    outlineVariant = OutlineVariantLight,
)
```

- [ ] **Step 2：将 DarkColors 替换为包含全部 token 的版本**

将文件中 `private val DarkColors = darkColorScheme(` 整块替换为：

```kotlin
private val DarkColors = darkColorScheme(
    primary = PrimaryDark,
    onPrimary = OnPrimaryDark,
    surface = SurfaceDark,
    onSurface = OnSurfaceDark,
    background = BackgroundDark,
    surfaceVariant = SurfaceVariantDark,
    onSurfaceVariant = OnSurfaceVariantDark,
    surfaceContainer = SurfaceContainerDark,
    surfaceContainerHighest = SurfaceContainerHighestDark,
    surfaceContainerLow = SurfaceContainerLowDark,
    primaryContainer = PrimaryContainerDark,
    error = ErrorDark,
    onError = OnErrorDark,
    errorContainer = ErrorContainerDark,
    onErrorContainer = OnErrorContainerDark,
    outlineVariant = OutlineVariantDark,
)
```

- [ ] **Step 3：编译验证**

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew compileDebugKotlin 2>&1 | tail -5
```

期望输出 `BUILD SUCCESSFUL`。

- [ ] **Step 4：提交**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/theme/SebastianTheme.kt
git commit -m "style(android): 补全 LightColors/DarkColors 覆盖全部 M3 token

消除 surfaceContainer、errorContainer、outlineVariant 等 fallback 紫色

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3：新建 SebastianSwitch 公共组件

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/SebastianSwitch.kt`

- [ ] **Step 1：创建文件**

```kotlin
package com.sebastian.android.ui.common

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import com.sebastian.android.ui.theme.SwitchCheckedDark
import com.sebastian.android.ui.theme.SwitchCheckedLight

/**
 * 苹果风格绿色开关，签名与 Material3 Switch 一致。
 * 跟随系统 dark/light 模式自动切换色值。
 */
@Composable
fun SebastianSwitch(
    checked: Boolean,
    onCheckedChange: ((Boolean) -> Unit)?,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val checkedTrack = if (isSystemInDarkTheme()) SwitchCheckedDark else SwitchCheckedLight
    Switch(
        checked = checked,
        onCheckedChange = onCheckedChange,
        modifier = modifier,
        enabled = enabled,
        colors = SwitchDefaults.colors(
            checkedThumbColor = Color.White,
            checkedTrackColor = checkedTrack,
            checkedBorderColor = Color.Transparent,
        ),
    )
}
```

- [ ] **Step 2：编译验证**

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew compileDebugKotlin 2>&1 | tail -5
```

期望输出 `BUILD SUCCESSFUL`。

- [ ] **Step 3：提交**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/SebastianSwitch.kt
git commit -m "feat(android): 新建 SebastianSwitch 苹果绿开关公共组件

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4：替换 3 处 Switch 为 SebastianSwitch

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AppearancePage.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/DebugLoggingPage.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderFormPage.kt`

- [ ] **Step 1：AppearancePage.kt — 替换 import 和调用**

将 import 行：
```kotlin
import androidx.compose.material3.Switch
```
替换为：
```kotlin
import com.sebastian.android.ui.common.SebastianSwitch
```

将文件中所有 `Switch(` 调用（共 1 处）改为 `SebastianSwitch(`，参数不变。

- [ ] **Step 2：DebugLoggingPage.kt — 替换 import 和调用**

将 import 行：
```kotlin
import androidx.compose.material3.Switch
```
替换为：
```kotlin
import com.sebastian.android.ui.common.SebastianSwitch
```

将文件中所有 `Switch(` 调用（共 1 处）改为 `SebastianSwitch(`，参数不变。

- [ ] **Step 3：ProviderFormPage.kt — 替换 import 和调用**

将 import 行：
```kotlin
import androidx.compose.material3.Switch
```
替换为：
```kotlin
import com.sebastian.android.ui.common.SebastianSwitch
```

将文件中所有 `Switch(` 调用（共 1 处）改为 `SebastianSwitch(`，参数不变。

> **注意**：如果 ProviderFormPage.kt 中有 `SwitchDefaults` 相关代码，一并删除（由 SebastianSwitch 内部处理）。

- [ ] **Step 4：编译验证**

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew compileDebugKotlin 2>&1 | tail -5
```

期望输出 `BUILD SUCCESSFUL`，无 unresolved reference 错误。

- [ ] **Step 5：提交**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add \
  ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AppearancePage.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/DebugLoggingPage.kt \
  ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderFormPage.kt
git commit -m "refactor(android): Switch → SebastianSwitch（苹果绿开关）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5：ThinkButton 去硬编码 iOS 蓝色

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/ThinkButton.kt`

- [ ] **Step 1：替换 3 处硬编码颜色**

将文件第 75-88 行的三个颜色变量替换为：

```kotlin
val backgroundColor = if (isActive && capability != ThinkingCapability.ALWAYS_ON)
    MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
else
    MaterialTheme.colorScheme.onSurface.copy(alpha = 0.08f)

val borderColor = if (isActive && capability != ThinkingCapability.ALWAYS_ON)
    MaterialTheme.colorScheme.primary.copy(alpha = 0.32f)
else
    MaterialTheme.colorScheme.onSurface.copy(alpha = 0.12f)

val contentColor = if (isActive && capability != ThinkingCapability.ALWAYS_ON)
    MaterialTheme.colorScheme.primary
else
    MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f)
```

同时移除顶部不再需要的 import：
```kotlin
import androidx.compose.ui.graphics.Color
```

> **注意**：移除 `Color` import 前先确认文件中没有其他地方用到 `Color(...)`，若有则保留 import。

- [ ] **Step 2：编译验证**

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew compileDebugKotlin 2>&1 | tail -5
```

期望输出 `BUILD SUCCESSFUL`。

- [ ] **Step 3：提交**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/ThinkButton.kt
git commit -m "fix(android): ThinkButton 激活色改用 colorScheme.primary 跟随主题

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6：GlobalApprovalBanner 去硬编码 Deny 红色

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/GlobalApprovalBanner.kt`

- [ ] **Step 1：替换第 166 行硬编码红色**

将：
```kotlin
containerColor = Color(0xFFB71C1C).copy(alpha = 0.82f),
```
替换为：
```kotlin
containerColor = MaterialTheme.colorScheme.error.copy(alpha = 0.82f),
```

- [ ] **Step 2：检查 Color import 是否可以移除**

检查 `GlobalApprovalBanner.kt` 中是否还有其他 `Color(...)` 直接调用（第 76 行有 `Color.Black`，第 174 行有 `Color.White`，第 198 行有 `Color.White`）。`Color.Black` / `Color.White` 仍需要 `import androidx.compose.ui.graphics.Color`，**保留该 import**。

- [ ] **Step 3：编译验证**

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew compileDebugKotlin 2>&1 | tail -5
```

期望输出 `BUILD SUCCESSFUL`。

- [ ] **Step 4：提交**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/GlobalApprovalBanner.kt
git commit -m "fix(android): Deny 按钮改用 colorScheme.error 跟随日/夜间主题

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7：最终全量构建验证

- [ ] **Step 1：全量编译**

```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew assembleDebug 2>&1 | tail -10
```

期望输出 `BUILD SUCCESSFUL`，生成 `app/build/outputs/apk/debug/app-debug.apk`。

- [ ] **Step 2：人工视觉验证清单**

安装到设备/模拟器后逐项确认：

| 场景 | 期望 |
|---|---|
| 连接与账户页（日间） | 卡片背景浅灰 `#F1F3F4`，无紫色 |
| 连接与账户页（夜间） | 卡片背景深灰 `#292B2D`，无紫色 |
| 退出登录按钮（日间） | 背景浅粉红 `#FFDAD6`，文字深红 |
| 退出登录按钮（夜间） | 背景深红 `#93000A` |
| 外观设置 Switch（日间/夜间） | 开启时苹果绿 |
| 调试日志 Switch | 开启时苹果绿 |
| Provider 设置 Switch | 开启时苹果绿 |
| ThinkButton 激活（日间） | 蓝色 `#1A73E8` 色系，非 iOS `#007AFF` |
| ThinkButton 激活（夜间） | 浅蓝 `#8AB4F8` 色系 |
| 审批面板 Deny 按钮（夜间） | 清晰可见红色 |
| Composer 输入框 | 外观无变化（透明底） |
| 审批面板 Allow 按钮 | 外观无变化（蓝色） |
