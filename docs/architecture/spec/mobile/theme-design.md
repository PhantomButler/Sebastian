---
version: "1.0"
last_updated: 2026-04-23
status: implemented
---

# Android 主题颜色体系

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 背景

`SebastianTheme.kt` 的 `LightColors` / `DarkColors` 原先只覆盖 Material3 颜色系统的 7 个 token，其余 fallback 到 M3 默认紫色种子方案，导致 `ConnectionPage` 卡片、分割线、输入框容器等处呈现紫色。此外部分组件使用硬编码颜色，不跟随日/夜间主题。

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
| `ErrorContainerLight` | `#FFDAD6` | 错误浅容器（errorContainer） |
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

> **实现增强**：Color.kt 额外包含 `AgentAccentLight`/`AgentAccentDark`、`AgentRainbowPurpleLight`/`AgentRainbowCyanLight` 等颜色常量，用于 Sub-Agent 头像色环，超出本 spec 原始范围。

---

## SebastianTheme 更新

`LightColors` 和 `DarkColors` 各追加 9 个 token：

```kotlin
surfaceContainer, surfaceContainerHighest, surfaceContainerLow,
primaryContainer, error, onError, errorContainer, onErrorContainer,
outlineVariant
```

补全后所有页面自动生效，无需改动业务页面代码。

---

## SebastianSwitch 公共组件

文件：`ui/common/SebastianSwitch.kt`

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
- checked：track = 苹果绿，thumb = 白色
- unchecked：沿用 `MaterialTheme.colorScheme.surfaceVariant`（灰色）
- 实现：`Switch` + `SwitchDefaults.colors(...)`

使用位置（全部替换原始 `Switch`）：

| 页面 | 文件 |
|------|------|
| 外观设置 | `ui/settings/AppearancePage.kt` |
| 调试日志 | `ui/settings/DebugLoggingPage.kt` |
| Provider 编辑 | `ui/settings/ProviderFormPage.kt` |
| 记忆设置 | `ui/settings/MemorySettingsPage.kt` |
| Effort 滑块 | `ui/settings/EffortSlider.kt` |

---

## 硬编码颜色修复

| 组件 | 修改前 | 修改后 |
|------|--------|--------|
| `GlobalApprovalBanner` Deny 按钮 | `Color(0xFFB71C1C).copy(alpha=0.82f)` | `MaterialTheme.colorScheme.error.copy(alpha=0.82f)` |

> **实现差异**：原 spec 提及 `ThinkButton.kt` 中 3 处 `Color(0xFF007AFF)` 需改为 `MaterialTheme.colorScheme.primary`。实际代码中 `ThinkButton.kt` 已不存在——该功能下线，思考控制迁移至 `AgentBindingEditorPage.kt`。新页面已正确使用语义色。

---

## 不在范围内

- `ThinkingCard` 绿色脉冲指示器（语义色，保留）
- `ToolCallCard` 工具状态色（有意保留跨主题一致辨识度）
- 其他业务页面布局或功能改动

---

## 文件清单

### 新增

- `ui/common/SebastianSwitch.kt`

### 修改

- `ui/theme/Color.kt` — 追加 20+ 颜色常量
- `ui/theme/SebastianTheme.kt` — LightColors / DarkColors 各追加 9 token
- `ui/common/GlobalApprovalBanner.kt` — 硬编码深红 → `colorScheme.error`
- `ui/settings/AppearancePage.kt` — `Switch` → `SebastianSwitch`
- `ui/settings/DebugLoggingPage.kt` — 同上
- `ui/settings/ProviderFormPage.kt` — 同上

---

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
