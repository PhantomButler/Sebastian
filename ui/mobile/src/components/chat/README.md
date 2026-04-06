# components/chat/

> 上级：[components/](../README.md)

## 目录职责

Sebastian 主对话页的 UI 组件集合，负责消息列表渲染、流式气泡显示、输入框交互和历史 Session 侧边栏。

## 目录结构

```
chat/
├── ChatSidebar.tsx       # 左侧历史 Session 列表侧边栏
├── MessageList.tsx       # 消息列表容器（滚动、历史消息渲染）
├── MessageBubble.tsx     # 单条消息气泡（user / assistant，已完成消息）
├── StreamingBubble.tsx   # 流式响应气泡（thinking block / text block / 工具调用实时展示）
└── MessageInput.tsx      # 底部输入框（发送、中断）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 修改历史 Session 侧边栏样式或交互 | [ChatSidebar.tsx](ChatSidebar.tsx) |
| 修改消息列表滚动行为或排列方式 | [MessageList.tsx](MessageList.tsx) |
| 修改已完成消息气泡样式（user/assistant） | [MessageBubble.tsx](MessageBubble.tsx) |
| 修改流式输出渲染（thinking/工具调用/文本） | [StreamingBubble.tsx](StreamingBubble.tsx) |
| 修改输入框交互（发送、中断、占位文字） | [MessageInput.tsx](MessageInput.tsx) |

---

> 修改本目录后，请同步更新此 README。
