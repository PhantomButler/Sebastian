# tests

> 上级索引：[项目根目录](../INDEX.md)

## 目录职责

存放 Sebastian 项目的全部自动化测试，按测试类型分为三层：单元测试（unit）、集成测试（integration）和端到端测试（e2e）。使用 `pytest` + `pytest-asyncio` 框架，`conftest.py` 提供共享 Fixture。

## 目录结构

```
tests/
├── __init__.py          # 包入口（空）
├── conftest.py          # 共享 Fixture（anyio_backend、db_session 内存数据库）
├── unit/                # 单元测试（隔离、纯逻辑、无真实 IO）
│   ├── test_a2a_dispatcher.py
│   ├── test_base_agent.py
│   ├── test_event_bus.py
│   ├── test_task_manager.py
│   └── ...（共 30+ 个测试文件）
├── integration/         # 集成测试（真实 SQLite、真实 FastAPI 路由）
│   ├── test_gateway_stream.py
│   ├── test_gateway_turns.py
│   ├── test_permission_flow.py
│   └── ...（共 10+ 个测试文件）
└── e2e/                 # 端到端测试（完整请求链路，当前预留）
```

## 三层测试说明

| 类型 | 目录 | 特点 | 适用场景 |
|------|------|------|---------|
| 单元测试 | `unit/` | Mock 外部依赖，运行极快 | 单个类/函数的逻辑验证 |
| 集成测试 | `integration/` | 真实 SQLite（不 Mock 数据库），真实路由 | 模块协作、API 行为验证 |
| 端到端测试 | `e2e/` | 覆盖完整请求链路 | 用户场景级别的行为验证 |

## 运行命令

```bash
# 全量运行
pytest

# 单独运行某一层
pytest tests/unit/
pytest tests/integration/
pytest tests/e2e/

# 运行单个文件
pytest tests/unit/test_base_agent.py

# 带详细输出
pytest -s -v tests/unit/test_task_manager.py

# 带覆盖率报告
pytest --cov=sebastian tests/
```

## 共享 Fixture（conftest.py）

| Fixture | 作用 |
|---------|------|
| `anyio_backend` | 指定 asyncio 后端（供 pytest-asyncio 使用） |
| `db_session` | 提供内存 SQLite 异步会话，测试结束自动销毁 |

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 共享 Fixture（数据库、事件循环配置） | [conftest.py](conftest.py) |
| 某个模块的单元测试 | [unit/](unit/) 下对应 `test_<module>.py` |
| Gateway / API 集成行为 | [integration/](integration/) 下对应文件 |

---

> 修改本目录或模块后，请同步更新此 README。
