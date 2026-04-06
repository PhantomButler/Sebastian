# src/

> 上级：[ui/mobile/](../README.md)

## 目录职责

移动端业务逻辑层，包含 API 请求封装、UI 组件、React Hooks 和 Zustand 状态管理。`app/` 目录（Expo Router 页面）通过引用本层模块组合出完整页面；`src/` 本身不包含路由逻辑。

## 目录结构

```
src/
├── api/          # HTTP / SSE 请求封装（每文件对应一类后端资源）
├── components/   # UI 组件（按业务域分组：chat/common/conversation/settings/subagents）
├── hooks/        # React Query 查询与 SSE 订阅封装
├── store/        # Zustand 本地 UI 状态（含 SecureStore 持久化配置）
├── screens/      # 屏幕级组件占位（当前空目录，预留未来拆分）
└── types.ts      # 前端共享 TypeScript 类型定义
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 后端接口调用 / SSE 连接协议 | [api/](api/README.md) |
| 页面 UI 组件 | [components/](components/README.md) |
| 数据获取 / 事件订阅 hooks | [hooks/](hooks/README.md) |
| 本地状态 / 持久化配置 | [store/](store/README.md) |
| 前端共享类型（接口数据结构等） | [types.ts](types.ts) |

## 子模块

- [api/](api/README.md) — HTTP / SSE 请求封装层
- [components/](components/README.md) — UI 组件（按业务域分组）
- [hooks/](hooks/README.md) — React Query 与 SSE 订阅 hooks
- [store/](store/README.md) — Zustand 本地 UI 状态管理
- `screens/` — 屏幕级组件（当前空目录，预留占位）

---

> 修改本目录后，请同步更新此 README。
