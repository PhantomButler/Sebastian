# components/chat/

> 上级：[components/](../README.md)

## 目录职责

Sebastian 主对话页的 UI 组件集合，负责消息列表渲染、流式气泡显示、输入框交互和侧边栏内容。

## 目录结构

```
chat/
├── AppSidebar.tsx        # 左侧边栏内容（功能入口区 + 历史对话区 + 新对话按钮）
├── TodoSidebar.tsx       # 右侧 Todo 侧边栏内容（任务区 + Todo 区，session 级绑定）
├── MessageList.tsx       # 消息列表容器（滚动、历史消息渲染）
├── MessageBubble.tsx     # 单条消息气泡（user / assistant，已完成消息）
├── StreamingBubble.tsx   # 流式响应气泡（thinking block / text block / 工具调用实时展示）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 修改左侧边栏功能入口、历史列表或新对话按钮 | [AppSidebar.tsx](AppSidebar.tsx) |
| 修改右侧 Todo 侧边栏内容（任务区 / Todo 区） | [TodoSidebar.tsx](TodoSidebar.tsx) |
| 修改消息列表滚动行为或排列方式 | [MessageList.tsx](MessageList.tsx) |
| 修改已完成消息气泡样式（user/assistant，主题化颜色） | [MessageBubble.tsx](MessageBubble.tsx) |
| 修改流式输出渲染（thinking/工具调用/文本，主题化颜色） | [StreamingBubble.tsx](StreamingBubble.tsx) |

---

> 修改本目录后，请同步更新此 README。
