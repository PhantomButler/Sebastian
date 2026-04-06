# sandbox

> 上级索引：[sebastian/](../README.md)

## 模块职责

提供安全的代码执行沙箱，对 Dynamic Tool Factory 等动态生成的代码进行 Docker 隔离执行，防止任意代码逃逸至宿主系统。当前处于**初始占位阶段**，`__init__.py` 为空模块；完整的 `executor.py` 尚未实现，但架构已规划（见 CLAUDE.md 安全规范：所有动态生成代码必须经本模块执行，禁止直接 `exec()`）。

## 目录结构

```
sandbox/
└── __init__.py    # 占位入口，当前为空（executor 待实现）
```

## 安全规范

- 所有动态生成或不受信任的代码，**必须**通过本模块的 `executor.py` 执行
- **禁止**在任何其他模块直接调用 `exec()` 或 `eval()`
- 沙箱执行需要 Docker 环境，并受 `SEBASTIAN_SANDBOX_ENABLED` 配置开关控制

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 代码沙箱执行器（待实现） | 在本目录新建 `executor.py`，封装 Docker 容器调用 |
| 沙箱开关配置 | [../config/__init__.py](../config/__init__.py) — `sebastian_sandbox_enabled` 字段 |
| 高危操作的 Approval 机制 | 在本目录新建 `approval.py`，对接 gateway 审批流 |

---

> 修改本目录或模块后，请同步更新此 README。
