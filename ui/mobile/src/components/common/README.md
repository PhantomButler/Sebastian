# components/common/

> 上级：[components/](../README.md)

## 目录职责

跨领域复用的通用 UI 组件，供 chat、subagents、settings 等多个业务域共同使用，不包含任何特定业务逻辑。

## 目录结构

```
common/
├── Sidebar.tsx                 # 通用侧边栏容器（左右通用，由 side prop 控制方向）
├── ContentPanGestureArea.tsx   # 页面级横向 pan 手势识别区（左右滑切换左右侧边栏）
├── ApprovalModal.tsx           # 审批弹窗（高危操作确认）
├── EmptyState.tsx              # 空状态占位组件（列表为空时展示）
├── Icons.tsx                   # 图标集合（统一管理所有图标引用）
└── StatusBadge.tsx             # 状态徽章（通用状态颜色 / 文字映射）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 修改侧边栏动画或手势交互（左右通用，`side` prop 控制方向） | [Sidebar.tsx](Sidebar.tsx) |
| 修改页面级横向 pan 手势识别（活动阈值/纵向让出） | [ContentPanGestureArea.tsx](ContentPanGestureArea.tsx) |
| 修改审批弹窗内容或按钮文案 | [ApprovalModal.tsx](ApprovalModal.tsx) |
| 修改空状态文案或插图 | [EmptyState.tsx](EmptyState.tsx) |
| 增删图标或修改图标尺寸 | [Icons.tsx](Icons.tsx) |
| 修改通用状态徽章颜色或文字 | [StatusBadge.tsx](StatusBadge.tsx) |

---

> 修改本目录后，请同步更新此 README。
