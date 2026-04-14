# Glass 液态玻璃组件库

> 上级：[common/README.md](../README.md)

基于 [`io.github.kyant0:backdrop`](https://github.com/Kyant0/AndroidLiquidGlass)（`backdrop:1.0.6`）封装的液态玻璃 UI 组件集。
调用方**无需**直接接触 backdrop 库 API。

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `GlassKit.kt` | 核心：`GlassState`、`rememberGlassState` |
| `GlassSurface.kt` | 带模糊采样的玻璃容器（大面积面板） |
| `GlassButton.kt` | 圆形玻璃按钮（`GlassCircleButton`） |
| `UniformShadow.kt` | `Modifier.uniformShadow()` 均匀四周投影扩展 |

---

## 快速上手

### 第一步：创建 GlassState

在需要玻璃效果的视图层**调用一次**：

```kotlin
val glassState = rememberGlassState(
    backgroundColor = MaterialTheme.colorScheme.background
)
```

### 第二步：标记被采样的内容层

把 `glassState.contentModifier` 应用到玻璃框**背后**的内容上。
只有打了这个标记的层才会被采样进模糊效果。

```kotlin
Box {
    MessageList(
        modifier = Modifier
            .fillMaxSize()
            .then(glassState.contentModifier)   // ← 关键：标记采样层
    )
    GlassSurface(state = glassState) { /* 玻璃内容 */ }
}
```

### 第三步：使用玻璃组件

---

## 组件 API

### `GlassSurface` — 玻璃容器

带背景模糊采样的大面积玻璃面板，适合输入框、底部栏、浮层等。

```kotlin
GlassSurface(
    state = glassState,
    shape = RoundedCornerShape(24.dp),   // 默认值，可自定义
    surfaceAlpha = 0.5f,                 // 表面叠加透明度（0~1）
    blurRadius = 20f,                    // 模糊半径
    modifier = Modifier
        .align(Alignment.BottomCenter)
        .padding(horizontal = 16.dp, vertical = 4.dp),
) {
    // 玻璃框内的内容
}
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `state` | `GlassState` | **必填** | 由 `rememberGlassState` 创建 |
| `shape` | `Shape` | `RoundedCornerShape(24.dp)` | 玻璃形状，同时用于裁剪和模糊边界 |
| `blurRadius` | `Float` | `GlassDefaults.BlurRadius`（20f） | 背景模糊强度，值越大越虚化 |
| `surfaceAlpha` | `Float` | `GlassDefaults.SurfaceAlpha`（0.5f） | 表面颜色叠加层透明度 |
| `shadowElevation` | `Dp` | `6.dp` | 均匀四周阴影半径（0 = 无阴影） |
| `shadowCornerRadius` | `Dp` | `24.dp` | 阴影圆角，**需与 `shape` 圆角对齐**（否则阴影不贴边） |
| `shadowColor` | `Color` | `Black α=0.18` | 阴影颜色 |

> ⚠️ **外层不要再 `.clip()`**：若调用方在 `GlassSurface` 外再套一层 `Modifier.clip(...)`，会把阴影裁掉。需要裁剪点击区域时，把 `.clip().clickable()` 放到 `GlassSurface` 的 **content 内部**（参见 [ChatScreen.kt](../../chat/ChatScreen.kt) 顶部左右按钮实现）。

---

### `Modifier.uniformShadow` — 均匀四周投影

独立可用的阴影扩展，适合给非 `GlassSurface` 的控件（如 `GlassCircleButton`、自定义浮动按钮）添加四周均匀阴影。

与 Android 原生 `Modifier.shadow` 的区别：
- 原生 `shadow` 基于 elevation 光源模型，**顶部阴影极淡**
- `uniformShadow` 用 `Paint.setShadowLayer(dx=0, dy=0)` 自绘，**四周等强度**

```kotlin
GlassCircleButton(
    onClick = { … },
    modifier = Modifier.uniformShadow(
        elevation = 4.dp,
        cornerRadius = 22.dp,   // CircleShape 44dp → size/2
    ),
) { Icon(…) }
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `elevation` | `Dp` | **必填** | 阴影模糊半径（0 = 不绘制） |
| `cornerRadius` | `Dp` | **必填** | 阴影圆角，需与控件 clip 形状一致 |
| `color` | `Color` | `Black α=0.18` | 阴影颜色 |

---

### `GlassCircleButton` — 圆形玻璃按钮

视觉玻璃风格（半透明 + 细描边），适合放在 `GlassSurface` 内部。
**不需要 `GlassState`**，不做模糊采样。

```kotlin
GlassCircleButton(
    onClick = { /* … */ },
    tint = GlassButtonTint.Primary,   // Neutral | Primary
    size = 44.dp,
    enabled = true,
) {
    Icon(
        imageVector = SebastianIcons.SendAction,
        contentDescription = "发送",
        tint = MaterialTheme.colorScheme.onPrimary,
    )
}
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `onClick` | `() -> Unit` | **必填** | 点击回调 |
| `tint` | `GlassButtonTint` | `Neutral` | `Neutral`（灰）/ `Primary`（主色填充）|
| `size` | `Dp` | `44.dp` | 按钮直径 |
| `enabled` | `Boolean` | `true` | 是否可交互 |
| `onLongClick` | `(() -> Unit)?` | `null` | 长按回调（Phase 3 语音预留）|

---

## 完整示例

```kotlin
@Composable
fun ChatArea(...) {
    val glassState = rememberGlassState(MaterialTheme.colorScheme.background)

    Box(modifier = Modifier.fillMaxSize()) {
        // 内容层：被玻璃采样
        MessageList(
            modifier = Modifier
                .fillMaxSize()
                .then(glassState.contentModifier),
        )

        // 玻璃容器
        GlassSurface(
            state = glassState,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(horizontal = 16.dp, vertical = 4.dp),
        ) {
            Column {
                TextField(...)
                Row {
                    // 玻璃圆形按钮（放在 GlassSurface 内部）
                    GlassCircleButton(
                        onClick = onSend,
                        tint = GlassButtonTint.Primary,
                    ) {
                        Icon(SebastianIcons.SendAction, contentDescription = "发送")
                    }
                }
            }
        }
    }
}
```

---

## 注意事项

1. **GlassState 不能跨屏幕复用**：backdrop 采样基于运行时布局位置，每个独立的视图区域应单独调用 `rememberGlassState`。

2. **内容层必须打标记**：忘记应用 `contentModifier` 时，玻璃只显示纯色叠层，看不到模糊内容，不报错但视觉不对。

3. **GlassCircleButton 放 GlassSurface 内效果最好**：单独使用时背后没有模糊内容，视觉玻璃感来自半透明本身，效果较弱。

4. **minSdk 要求**：backdrop 库使用 AGSL shader，需要 Android 12（API 31）+。本项目 minSdk = 33，满足要求。
