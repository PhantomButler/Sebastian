# theme 模块

> 上级：[ui/README.md](../README.md)

Material3 主题配置，统一品牌色与 Light / Dark 切换，组件内部不直接硬编码颜色。

## 目录结构

```text
theme/
├── Color.kt            # 品牌色与语义色 token
└── SebastianTheme.kt   # MaterialTheme 配置（Light / Dark）
```

## 模块说明

### `Color.kt`

定义品牌色（Primary / Secondary / Tertiary）和语义色 token（Background / Surface / Error 等）。组件引用 `MaterialTheme.colorScheme.*`，颜色来源由此文件统一管理。

### `SebastianTheme`

封装 Material3 `MaterialTheme`，根据系统 Dark Mode 状态切换 Light / Dark ColorScheme。所有 Screen 的根节点均包裹在 `SebastianTheme` 中（由 `MainActivity` 设置）。

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改品牌主色 / 强调色 | `Color.kt` |
| 改 Light / Dark ColorScheme | `SebastianTheme.kt` |
| 新增语义色 token | `Color.kt`（定义）+ 使用方通过 `MaterialTheme.colorScheme` 引用 |

---

> 修改主题色后，建议在模拟器分别验证 Light / Dark 两种模式的视觉效果，并同步更新本 README 与上级 [ui/README.md](../README.md)。
