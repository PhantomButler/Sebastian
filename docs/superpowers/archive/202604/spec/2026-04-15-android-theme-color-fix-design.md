---
integrated_to: mobile/theme-design.md
integrated_at: 2026-04-23
---

# Android 主题颜色补全 & SebastianSwitch 设计文档

**日期**：2026-04-15  
**状态**：已批准，待实现

---

## 问题描述

`SebastianTheme.kt` 的 `LightColors` / `DarkColors` 只覆盖了 Material3 颜色系统的 7 个 token，
其余 token（`surfaceContainer`、`errorContainer`、`outlineVariant` 等）fallback 到 M3 默认紫色种子方案。
截图可见 `ConnectionPage` 卡片背景、分割线、输入框容器呈现紫色。

额外问题：`ThinkButton`、`GlobalApprovalBanner` 存在硬编码颜色（iOS 蓝 / 深红），不跟随日/夜间主题；
所有 `Switch` 组件未定制颜色，显示默认蓝色，与 App 苹果风格不符。

---

## 目标

1. 补全 9 个缺失的 M3 颜色 token，消除紫色 fallback，所有页面自动生效，无需改动业务页面。
2. 修掉 2 处硬编码颜色（ThinkButton × 3、GlobalApprovalBanner × 1）。
3. 新建 `SebastianSwitch` 公共组件，封装苹果绿开关样式，统一 3 处用法。

---

## 不在范围内

- `ThinkingCard` 绿色脉冲指示器（语义色，保留）
- `ToolCallCard` 工具状态色（有意保留跨主题一致辨识度）
- 其他业务页面布局或功能改动

---

## 颜色方案

### 新增颜色常量（Color.kt）

#### 日间（Light）

| 常量名 | 色值 | 用途 |
|---|---|---|
| `SurfaceContainerLight` | `#F1F3F4` | 卡片背景（surfaceContainer） |
| `SurfaceContainerHighestLight` | `#E8EAED` | 输入框容器（surfaceContainerHighest） |
| `SurfaceContainerLowLight` | `#F8F9FA` | 低层级容器（surfaceContainerLow） |
| `PrimaryContainerLight` | `#D3E3FD` | 蓝色浅容器（primaryContainer） |
| `ErrorLight` | `#B00020` | 错误红（error） |
| `OnErrorLight` | `#FFFFFF` | 错误上文字（onError） |
| `ErrorContainerLight` | `#FFDAD6` | 错误浅容器（errorContainer，退出登录按钮背景） |
| `OnErrorContainerLight` | `#410002` | 错误容器上文字（onErrorContainer） |
| `OutlineVariantLight` | `#C7C7CC` | 分割线（outlineVariant） |
| `SwitchCheckedLight` | `#34C759` | 苹果绿开关（日间） |

#### 夜间（Dark）

| 常量名 | 色值 | 用途 |
|---|---|---|
| `SurfaceContainerDark` | `#292B2D` | 卡片背景 |
| `SurfaceContainerHighestDark` | `#36393B` | 输入框容器 |
| `SurfaceContainerLowDark` | `#252729` | 低层级容器 |
| `PrimaryContainerDark` | `#0A3266` | 蓝色深容器 |
| `ErrorDark` | `#CF6679` | 错误色 |
| `OnErrorDark` | `#690005` | 错误上文字 |
| `ErrorContainerDark` | `#93000A` | 错误深容器 |
| `OnErrorContainerDark` | `#FFDAD6` | 错误容器上文字 |
| `OutlineVariantDark` | `#3C3F41` | 分割线 |
| `SwitchCheckedDark` | `#30D158` | 苹果绿开关（夜间，更亮） |

---

## 文件改动清单

### 1. `ui/theme/Color.kt`（修改）

追加上述 20 个颜色常量。

### 2. `ui/theme/SebastianTheme.kt`（修改）

`LightColors` 追加：
```kotlin
surfaceContainer = SurfaceContainerLight,
surfaceContainerHighest = SurfaceContainerHighestLight,
surfaceContainerLow = SurfaceContainerLowLight,
primaryContainer = PrimaryContainerLight,
error = ErrorLight,
onError = OnErrorLight,
errorContainer = ErrorContainerLight,
onErrorContainer = OnErrorContainerLight,
outlineVariant = OutlineVariantLight,
```

`DarkColors` 追加对应夜间 9 个 token。

### 3. `ui/common/SebastianSwitch.kt`（新建）

```kotlin
@Composable
fun SebastianSwitch(
    checked: Boolean,
    onCheckedChange: ((Boolean) -> Unit)?,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
)
```

- 内部用 `isSystemInDarkTheme()` 选择 `SwitchCheckedLight` / `SwitchCheckedDark`
- checked 时：track = 苹果绿，thumb = 白色
- unchecked 时：沿用 `MaterialTheme.colorScheme.surfaceVariant`（灰色）
- 实现：`Switch` + `SwitchDefaults.colors(...)`

### 4. `ui/settings/AppearancePage.kt`（修改）

`Switch(...)` → `SebastianSwitch(...)`，参数不变。

### 5. `ui/settings/DebugLoggingPage.kt`（修改）

同上。

### 6. `ui/settings/ProviderFormPage.kt`（修改）

同上。

### 7. `ui/composer/ThinkButton.kt`（修改）

3 处 `Color(0xFF007AFF)` → `MaterialTheme.colorScheme.primary`。

### 8. `ui/common/GlobalApprovalBanner.kt`（修改）

1 处 `Color(0xFFB71C1C).copy(alpha = 0.82f)` → `MaterialTheme.colorScheme.error.copy(alpha = 0.82f)`。

---

## 验证标准

- `ConnectionPage` 卡片背景为浅灰（日间）/ 深灰（夜间），无紫色
- 退出登录按钮背景为浅红（日间）/ 深红（夜间），非紫色
- 所有 Switch 开关激活色为苹果绿
- ThinkButton 激活色跟随主题蓝（日间深蓝 / 夜间浅蓝）
- GlobalApprovalBanner Deny 按钮在夜间模式下仍清晰可见
- Composer 输入框、审批面板 Allow 按钮外观无变化

---

## 不改动文件

- `ThinkingCard.kt`（语义绿保留）
- `ToolCallCard.kt`（状态色有意保留）
- 所有其他业务页面

