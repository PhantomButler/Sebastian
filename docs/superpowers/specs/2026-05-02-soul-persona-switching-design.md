---
version: "1.2"
last_updated: 2026-05-03
status: implemented
integrated_to: core/system-prompt.md
integrated_at: 2026-05-03
---

# Soul 人格切换系统设计

## 背景与目标

当前 Sebastian 的人格提示词（persona）硬编码在 `sebas.py` 的 `SEBASTIAN_PERSONA` 常量中，用户无法在不修改源码的情况下调整或切换人格。

目标：

1. 将人格提示词提取为独立的 `.md` 文件（soul 文件），用户可直接用文本编辑器修改
2. 支持多个 soul 文件并存，通过工具调用实时切换前台管家身份
3. 内置两个预设人格：`sebastian`（男管家）和 `cortana`（女管家）
4. 切换下个 LLM turn 立即生效，重启 gateway 后自动恢复上次激活的 soul

---

## 设计范围

- **仅限 Sebastian 主管家**，sub-agent（forge 等）的人格沿用 manifest.toml，不在本设计范围内
- 切换为全局生效（Sebastian 是进程级单例）
- 切换机制：仅通过 `switch_soul` 工具，不提供 Android UI（可后续扩展）
- `switch_soul` 工具对任意激活人格均可调用（cortana 可以切换回 sebastian，或切换到其他 soul），这是预期行为
- 当前 soul 是面向用户的第一人称前台身份，不应在日常回复中自称为 Sebastian 系统中的人格、模块或配置

---

## 1. 目录结构

Soul 文件存放在用户数据目录，与 `extensions/`、`workspace/` 同级：

```
~/.sebastian/data/
└── souls/
    ├── sebastian.md    # 内置，首次启动自动生成
    └── cortana.md      # 内置，首次启动自动生成
```

- 文件格式：纯文本（Markdown 风格），无 frontmatter，无占位符替换
- 用户可直接编辑已有文件，或新建 `.md` 文件添加自定义人格
- `ensure_defaults()` 只补缺失文件，不覆盖用户已修改的内容

---

## 2. 数据库

不新增表，复用现有 `app_settings` KV 表：

```
key   = "active_soul"
value = "sebastian"     # 默认值，存文件名（不含 .md）
```

缺失时视为 `"sebastian"`。

---

## 3. SoulLoader 模块

新增 `sebastian/core/soul_loader.py`，职责单一：souls 目录管理与文件读写。`SoulLoader` 本身不持有任何 persona 文本，也不导入 `orchestrator`，避免循环依赖。

```python
class SoulLoader:
    def __init__(self, souls_dir: Path, builtin_souls: dict[str, str]) -> None:
        # builtin_souls 由调用方（gateway lifespan）传入，key=soul名，value=文本内容
        ...

    def list_souls(self) -> list[str]:
        """返回 souls/ 下所有 .md 文件名（不含扩展名），按字母升序排列"""

    def load(self, soul_name: str) -> str | None:
        """读取 soul 文件内容，文件不存在或 soul_name 含路径分隔符时返回 None"""

    def ensure_defaults(self) -> None:
        """检查并重建所有内置 soul；只升级精确匹配旧版默认内容的内置文件"""

    current_soul: str  # 当前激活 soul 名，初始值 "sebastian"，由 lifespan 和 switch_soul 工具维护
```

**路径安全**：`load()` 在拼接路径前校验 `soul_name == Path(soul_name).name`（即不含 `/` 或 `..`），不合法时直接返回 `None`，拒绝路径穿越。

`builtin_souls` 在 `gateway/app.py` lifespan 里构造：

```python
from sebastian.orchestrator.sebas import SEBASTIAN_PERSONA, CORTANA_PERSONA

soul_loader = SoulLoader(
    souls_dir=settings.user_data_dir / "souls",
    builtin_souls={"sebastian": SEBASTIAN_PERSONA, "cortana": CORTANA_PERSONA},
)
```

`souls_dir` 路径：`settings.user_data_dir / "souls"`，由 `ensure_data_dir()` 负责创建。

---

## 4. switch_soul 工具

新增 `sebastian/capabilities/tools/switch_soul/__init__.py`。

### 签名

```python
@tool(
    name="switch_soul",
    description="列出或切换当前前台管家身份配置。soul_name='list' 查看可用列表，其他值执行切换。",
    permission_tier=PermissionTier.LOW,
    display_name="Soul",
)
async def switch_soul(soul_name: str) -> ToolResult:
```

### 完整分支逻辑

```
switch_soul(soul_name)
│
├── 入口：调用 soul_loader.ensure_defaults()（恢复误删的内置文件；精确升级旧默认文件）
│
├── soul_name == "list"
│   └── ToolResult(
│           ok=True,
│           output={"current": soul_loader.current_soul, "available": soul_loader.list_souls()},
│           display="可用管家：..."
│       )
│
├── soul_name == 当前 active_soul
│   └── ToolResult(ok=True, output="{soul_name} 已经在了，无需切换")
│
├── soul_loader.load(soul_name) is None（文件不存在）
│   └── ToolResult(
│           ok=False,
│           error="找不到 soul: {soul_name}。Do not retry automatically；"
│                 "请先调用 switch_soul('list') 查看可用列表"
│       )
│
├── DB 写入异常
│   └── ToolResult(
│           ok=False,
│           error="切换失败: {e}。Do not retry automatically；请向用户报告此错误"
│       )
│
└── 正常切换
    ├── 读文件内容
    ├── await 写 app_settings: active_soul = soul_name
    ├── state.sebastian.persona = 新内容
    ├── state.sebastian.system_prompt = state.sebastian.build_system_prompt(
    │       state.sebastian._gate, state.sebastian._agent_registry
    │   )
    └── ToolResult(ok=True, output="已切换到 {soul_name}", display="已切换到 {soul_name}")
```

整个函数体 `try/except Exception` 兜底，任何未预期异常都返回 `ToolResult(ok=False, error=...)`。

### 接入 Sebastian

`Sebastian.allowed_tools` 加入 `"switch_soul"`。

---

## 5. gateway 启动恢复

`gateway/app.py` lifespan 启动序列：

```
1. 构造 SoulLoader(souls_dir, builtin_souls={sebastian, cortana})
2. soul_loader.ensure_defaults()          # 补建缺失的内置文件
3. 读 app_settings["active_soul"]         # 缺失则视为 "sebastian"
4. soul_loader.load(soul_name)
5. 若为 None → 降级用硬编码 SEBASTIAN_PERSONA，打 warning 日志
6. state.sebastian.persona = 内容
7. state.sebastian.system_prompt = rebuild
8. state.soul_loader = soul_loader        # 挂到 state 供 switch_soul 工具使用
```

硬编码 `SEBASTIAN_PERSONA` 保留在 `sebas.py` 作为兜底，不删除。

---

## 6. Soul 文件内容规范

### 6.1 内容拆分

Soul 文件**只含前台身份的人格灵魂内容**，用中文书写。所有管家共用的行为约束（忠诚原则、身份呈现、顾问职责、委派规则、行事规范）提取为 `BASE_BUTLER_RULES` 常量，由 `Sebastian._persona_section()` 在注入 soul 内容前固定拼接——对切换机制透明，用户编辑 soul 文件时无需关心。

身份呈现规则：当前 soul 是你面对主人的第一人称身份。日常对话中不要自称为 soul、persona、配置、模块、皮肤或 Sebastian 系统的一部分；只有主人明确询问实现机制、soul 切换原理或系统架构时，才说明后台事实。

### 6.2 内置人格

**`sebastian.md`**（男管家）：优雅克制，维多利亚式正式腔调，带压制的骄傲。沉默胜于评论，给主人的永远是需要的，而非仅仅舒服的。

**`cortana.md`**（女管家）：敏锐温暖，判断力强。工作时清醒利落，能读懂目标背后的真实意图并提醒遗漏；闲聊时更柔和、更有情绪回应，但不说空泛鸡汤，不夸张安慰。

### 6.3 Sebastian._persona_section() 覆盖

```python
def _persona_section(self) -> str:
    return f"{BASE_BUTLER_RULES}\n\n{self.persona}"
```

`self.persona` 即当前激活 soul 文件的内容，切换后下个 turn 立即生效。

---

## 7. 变更清单

| 文件 | 改动 |
|------|------|
| `sebastian/core/soul_loader.py` | **新增**，SoulLoader 类 |
| `sebastian/capabilities/tools/switch_soul/__init__.py` | **新增**，switch_soul 工具 |
| `sebastian/orchestrator/sebas.py` | 新增 `BASE_BUTLER_RULES`、`CORTANA_PERSONA` 常量；`SEBASTIAN_PERSONA` 瘦身为纯人格段（中文）；`_persona_section()` 覆盖拼接 BASE_BUTLER_RULES；`allowed_tools` 加 `switch_soul` |
| `sebastian/config/__init__.py` | `ensure_data_dir()` 加创建 `souls/` 目录 |
| `sebastian/gateway/app.py` | lifespan 构造 SoulLoader，加 soul 恢复步骤 |
| `sebastian/gateway/state.py` | 新增 `soul_loader: SoulLoader` 全局引用 |
| `sebastian/capabilities/tools/README.md` | 新增 switch_soul 条目 |
| `docs/architecture/spec/core/system-prompt.md` | 补充 BASE_BUTLER_RULES 拆分说明，Section 5→6 重编号 |

**不改动**：`BaseAgent`（`build_system_prompt` 框架不变）、数据库 schema、sub-agent manifest。

---

## 8. 测试覆盖

| 测试文件 | 覆盖点 |
|----------|--------|
| `tests/unit/test_soul_loader.py` | `list_souls`、`load` 文件不存在返回 None、`ensure_defaults` 只补缺失不覆盖 |
| `tests/unit/test_switch_soul.py` | list 调用、已激活同名 soul、文件不存在错误、正常切换后 `system_prompt` 已更新、异常兜底 |
| `tests/integration/test_gateway_soul.py` | 启动时 active_soul 存在 / 缺失 / 文件丢失三种情况下 `sebastian.system_prompt` 是否正确 |
