# Mobile 开发踩坑记录

> 面向 `ui/mobile/`（React Native / Expo / Android）的平台行为坑与修复结论。
> 每条记录包含：现象、根因、结论/修复。

**相关导航**：[ui/mobile/README.md](../../ui/mobile/README.md)

---

## 1. Android touch hit-test 与 transform 不联动

**日期**：2026-04-10  
**涉及文件**：`ui/mobile/src/components/common/SwipePager.tsx`

### 现象

主对话页 FlatList 完全无法上下滚动，内容可见但触摸无响应。  
SubAgent 页的 FlatList 正常，两页使用完全相同的 `SwipePager` + `ConversationView` 组件。

### 根因

Android touch hit-test 使用 **layout 坐标**，不受 `transform: translateX` 影响。

`SwipePager` 旧实现用 flex-row `Animated.View` (track) + 整体 `translateX` 实现三面板平移。有左侧栏时初始 `translateX = -sidebarPx`，视觉上中心面板在 x=0，但 layout 坐标不变：

| 面板 | layout x | 视觉 x（中心状态） |
|------|---------|-----------------|
| 左侧 | 0..sidebarPx (≈0..320px) | -320px（屏外） |
| 中心 | sidebarPx..sidebarPx+screenW | 0..screenW ← 视觉在这 |
| 右侧 | sidebarPx+screenW.. | screenW..（屏外） |

左侧面板 layout 覆盖屏幕约 80% 宽度（x=0..320），导致这 80% 区域的触摸事件全被左侧面板拦截，FlatList 收不到任何竖向滑动。

SubAgent 页没有左侧栏，`translateX=0`，layout 与视觉一致，不受影响——这是两页行为不同的直接原因。

### 修复

三面板改为**绝对定位**，确保各面板 layout 坐标与其**激活时的视觉坐标**完全对齐：

| 面板 | 绝对定位 | 激活时 layout = 激活时视觉 |
|------|---------|--------------------------|
| 左侧 | `position: absolute, left: 0, width: sidebarPx` | x=0..sidebarPx ✓ |
| 中心 | `position: absolute, left: 0, width: screenW` | x=0..screenW ✓ |
| 右侧 | `position: absolute, right: 0, width: sidebarPx` | x=screenW-sidebarPx..screenW ✓ |

> **右侧面板必须用 `right: 0`**，用 `left: 0` 的话 layout 在 x=0..sidebarPx，与激活时视觉不符，右侧 sidebar 右边约 20% 区域不可点击。

各面板的 `translateX` 完全复刻原 flex-row track 的推移视觉效果：

```
tv = Reanimated 共享值（snapPoints 驱动）

左侧  translateX = tv
中心  translateX = tv + (hasLeft ? sidebarPx : 0)
右侧  translateX = tv + (hasLeft ? 2 : 1) * sidebarPx
```

非激活面板设置 `pointerEvents="none"`，激活面板触摸正常。

### 结论

> **在 React Native Android 上，永远不要依赖 `transform` 来移动可交互区域。**  
> Hit-test 只认 layout 坐标。需要触摸的地方，layout 必须在正确位置。

---

<!-- 新增记录请在此之后按相同格式追加 -->
