---
version: "1.1"
last_updated: 2026-04-23
status: in-progress
---

# Sebastian Android 原生客户端 Spec 索引

*← [Spec 根索引](../INDEX.md)*

---

## 定位

本目录对应 `ui/mobile-android/` — Sebastian 的 Kotlin 原生 Android 客户端。  
与 `ui/mobile/`（React Native 旧版）并列存在，旧版保留作为功能参考。

**技术栈**：Kotlin + Jetpack Compose + Hilt + OkHttp + Retrofit  
**最低支持**：Android 13（API 33）  
**设计原则**：性能优先，交互体验对标贾维斯式自然感，架构面向 Phase 3+ 扩展预留

---

## Spec 文档

| Spec | 摘要 |
|------|------|
| [overview.md](overview.md) | 项目定位、技术栈决策、目录结构、Phase 功能规划、与后端协议对接约定 |
| [navigation.md](navigation.md) | ThreePaneScaffold 三面板导航、WindowSizeClass 自适应（手机覆盖/平板常驻）、页面路由结构 |
| [streaming.md](streaming.md) | SSE 连接稳定性架构、流式 Markdown 渲染（multiplatform-markdown-renderer 纯 Composable）、代码块高亮、ThinkingCard 极简风格、逐块淡入动画、滚动跟随逻辑 |
| [composer.md](composer.md) | Composer 插槽架构、Phase 1 实现、Phase 2-3 预留扩展路径（语音/附件/全双工）|
| [data-layer.md](data-layer.md) | Repository 分层、ViewModel + StateFlow、Hilt 注入、本地持久化（DataStore）|
| [global-approval.md](global-approval.md) | 全局审批系统（GlobalApprovalViewModel + Banner）、SubAgent 对话页复用 ChatScreen、路由变更 |
| [session-panel.md](session-panel.md) | Session 侧栏按日期分组（今天/昨天/7天/30天 + 年月折叠）、GroupHeader、折叠状态记忆、active 自动展开 |
| [theme-design.md](theme-design.md) | M3 颜色 token 补全（消除紫色 fallback）、SebastianSwitch 苹果绿组件、硬编码颜色修复 |

---

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改导航结构或三面板行为 | [navigation.md](navigation.md) |
| 改流式输出渲染或动画 | [streaming.md](streaming.md) |
| 改 SSE 连接/重连逻辑 | [streaming.md](streaming.md) |
| 改输入框、发送/停止、附件预留 | [composer.md](composer.md) |
| 改 ViewModel / Repository / 数据流 | [data-layer.md](data-layer.md) |
| 改全局审批、审批弹窗、审批队列 | [global-approval.md](global-approval.md) |
| 改 SubAgent 对话页、ChatScreen agentId | [global-approval.md](global-approval.md) |
| 查阅整体 Phase 规划或技术栈决策 | [overview.md](overview.md) |
| 改 Session 侧栏分组、折叠、日期显示 | [session-panel.md](session-panel.md) |
| 改主题颜色、Switch 组件、新增颜色 token | [theme-design.md](theme-design.md) |

---

*← [Spec 根索引](../INDEX.md)*
