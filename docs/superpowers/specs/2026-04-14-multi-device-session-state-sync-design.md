# 多设备 Session 状态同步：Session 状态机 + Turn 互斥

## Context

当前 SSE 广播底座（[sebastian/gateway/sse.py](../../../sebastian/gateway/sse.py)）已经天然支持多端同屏流式观看：

- 每个 SSE 连接独立 `_StreamSubscription`，EventBus 事件按 `session_id` 过滤后广播给所有订阅者
- `Last-Event-ID` + 500 条 ring buffer 支持断线重连回放
- 两台手机打开同一个 session，token 级同步流式输出

但**输入侧没有任何协调机制**，暴露出的问题：

1. A 手机和 B 手机同时按发送 → 产生两个并行 turn，LLM 抢话、上下文错乱
2. LLM 正在流式输出时，另一端可以继续 POST `/turns` → 同上
3. 有 approval 悬而未决时，任一端可以继续发消息 → 绕过审批语义

这是一个人机对话场景（不是 Telegram 的人人群聊），两台设备都是同一个 owner 的两个入口。真正的诉求是：**同一时刻 session 只能有一条"正在进行中"的交互**，所有端的 UI 对此状态保持一致。

**决策：引入 session 级状态机，orchestrator 单点驱动，通过现有 SSE 广播到所有端**。Turn 互斥通过输入框置灰（主）+ `POST /turns` 409 校验（兜底）实现。

## 非目标

- **不做 Draft 同步**：一个人两台手机的 draft 同步使用频率极低，状态机已经消除"抢话"这个真正的 bug，Draft 是锦上添花，观察实际需求后再议
- **不做 typing indicator**：人机对话里"对端"是 LLM，typing 无意义；设备间 typing 同步属于 draft 同步的延伸
- **不做服务端 turn 排队**：LLM 输出可能持续 30 秒以上，排着的消息可能早已过期失效，用户困惑大于收益。直接 409 + 前端置灰
- **不做多用户权限边界**：当前所有设备都是同一个 owner 账号，多用户隔离留给 Phase 5 identity
- **不做设备列表 / 踢下线管理**：非刚需，session 状态机已经解决主要冲突
- **不做消息编辑 / 撤销**：这是独立能力，不在本 spec 范围

## 架构

### 状态机定义

```
idle                    # 空闲，任何端都可发送
user_sending            # POST /turns 受理成功，排进 LLM 前的短暂过渡态
assistant_streaming     # LLM 正在流式输出
awaiting_approval       # 有 approval 悬而未决
```

转换规则（orchestrator 单点驱动）：

| 当前 | 事件 | 下一状态 |
|------|------|---------|
| `idle` | `POST /turns` 受理 | `user_sending` |
| `user_sending` | LLM 开始流式 | `assistant_streaming` |
| `assistant_streaming` | 触发 approval | `awaiting_approval` |
| `awaiting_approval` | approval 批准/拒绝 | `assistant_streaming` |
| `assistant_streaming` | turn 完成/失败/取消 | `idle` |
| `user_sending` | turn 失败（未进入 streaming） | `idle` |

### 存储位置

状态**只存内存**（SessionStore 或 orchestrator 的 in-memory session map），不落库：

- 进程重启后一定是 `idle`（重启时所有 turn 都被中断，语义自洽）
- 避免引入 SQLite schema 迁移
- 不需要跨进程共享（Sebastian 是单进程 gateway）

### 事件广播

新增 Event 类型 `SESSION_STATE`，payload：

```json
{
  "session_id": "...",
  "state": "assistant_streaming",
  "since_ts": "2026-04-14T12:34:56Z"
}
```

复用现有 EventBus → SSEManager 广播路径，所有订阅该 session 的端都实时收到。

### Gateway 兜底校验

`POST /turns` 处理开始处：

```python
if session.state != "idle":
    raise HTTPException(
        status_code=409,
        detail={"code": "session_busy", "state": session.state},
    )
```

正常情况下前端输入框已经置灰，用户按不到发送按钮。409 只应对"状态事件还没到、用户抢在前面按"的极端 race。

### 客户端 UI 行为

Android App 订阅 `session.state` 事件，根据状态切换输入框：

| state | 输入框 | 提示语 |
|-------|--------|--------|
| `idle` | 可用 | （无） |
| `user_sending` | 置灰 | "正在发送…" |
| `assistant_streaming` | 置灰 | "Sebastian 正在回复…" |
| `awaiting_approval` | 置灰 | "等待审批…" |

收到 409 时作为兜底兜住 race，按 detail 里的 state 立即更新 UI。

## 落地改动

| 改动 | 位置 | 规模 |
|------|------|------|
| SessionStore 增加 `state` 字段 + `set_state(session_id, state)` | [sebastian/store/](../../../sebastian/store/) | 小 |
| 新 Event 类型 `SESSION_STATE` | [sebastian/protocol/events/types.py](../../../sebastian/protocol/events/types.py) | 小 |
| Orchestrator turn 生命周期 4 处钩子发事件 | [sebastian/orchestrator/](../../../sebastian/orchestrator/) | 中 |
| `POST /turns` 加 409 校验 | [sebastian/gateway/routes/turns.py](../../../sebastian/gateway/routes/turns.py) | 小 |
| Approval 批准/拒绝路径回写状态 | [sebastian/gateway/routes/approvals.py](../../../sebastian/gateway/routes/approvals.py) | 小 |
| Android 订阅 `session.state` 事件 + 输入框状态 | [ui/mobile-android/](../../../ui/mobile-android/) | 中 |

整体一个 PR 边界清晰。

## 关键设计考量

### 为什么状态机由 orchestrator 单点驱动

避免 Gateway 和 orchestrator 两处都写状态，产生不一致。Gateway 只做：
- `POST /turns` 前读状态（兜底 409）
- 不主动 set 状态

所有状态变更都在 orchestrator 的 turn 生命周期钩子里完成。

### 为什么 `user_sending` 作为独立短暂过渡态

`POST /turns` 受理到 LLM 首个 chunk 之间可能有几百毫秒（建立 session、加载 prompt、首 token 延迟）。没有这个过渡态就会出现"我按了发送但 session 还是 idle，另一端又按了发送"的窗口。

### 为什么不用锁 / 信号量

状态机 + 事件广播是声明式的，所有端都能看到同一份 truth。锁是命令式的，只能在服务端内部生效，客户端无法感知→ UI 无法同步置灰。

### 数据一致性的保底

即使 `session.state` 事件丢失（ring buffer 满、客户端断线超出 buffer 范围）：

- 客户端重连时通过 `GET /api/v1/sessions/{id}/recent` 拉最新状态（需要在 response 里带上 `state` 字段）
- Gateway 的 409 校验确保即使 UI 状态过期，服务端也不会真的并发处理两个 turn

## 未来演进（不在本 spec 范围）

- Draft 同步（Telegram 式，观察需求后决定）
- 设备列表 / 踢下线（多用户隔离后再做）
- Session 级"这个消息是哪台设备发的"标记（调试有用，但当前单用户场景价值低）
