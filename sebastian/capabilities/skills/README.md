# skills

> 上级索引：[capabilities/](../README.md)

## 目录职责

管理 Skill（复合能力）的动态加载与注册。Gateway 启动时会扫描本目录及用户自定义目录下的各 Skill 子目录，读取 `SKILL.md` 描述文件，将 Skill 包装为 `skill__<name>` 格式的工具并注入 `CapabilityRegistry`。新会话的首轮 turn 会在模型请求前检查 `SKILL.md` 指纹变化并刷新当前 Agent 的 prompt / tool snapshot，**无需修改核心代码或重启服务**即可让新会话看到新增或修改后的 Skill。

## 目录结构

```
skills/
├── __init__.py        # 包入口（空）
├── _loader.py         # 扫描 SKILL.md、生成工具 spec
├── metadata.py        # 解析 SKILL.md frontmatter、校验 Skill 注册名
├── hot_reload.py      # 计算 SKILL.md 指纹，新会话首轮触发 Skill 热加载
└── skill_installer/   # 内置 Skill：通过 Sebastian CLI 管理 Skill 包
    └── SKILL.md
```

## Skill 定义格式

每个 Skill 是一个子目录，包含一个 `SKILL.md` 文件：

```
skills/
└── my_skill/
    └── SKILL.md
```

`SKILL.md` 支持 YAML frontmatter + Markdown 正文：

```markdown
---
name: my_skill
description: 这个 Skill 的简短描述
---

# 使用说明

详细的调用指导，会拼接到 description 后作为完整 instructions 传给 LLM。
```

加载规则：
- `name` 只能包含英文字母、数字、下划线和短横线，不能包含路径分隔、空格或点号
- `name` 必须写裸 Skill 名，不能包含 `skill__` 前缀
- 工具名统一注册为 `skill__<name>`
- 后加载的目录可覆盖同名 Skill（支持用户自定义覆盖内置 Skill）
- 目录名以 `_` 开头的子目录跳过（如 `_loader.py` 所在位置）
- 不合法的 Skill 会被跳过并记录 warning，不注入 `CapabilityRegistry`
- `allowed_skills` 必须使用完整注册名，例如 `skill__flight_search`，不要写裸名 `flight_search`

## 热加载生命周期

- Gateway 启动时完成一次全量 Skill 加载，并记录当前 `SKILL.md` 指纹。
- 每个新会话的首轮 turn 在组装 prompt 和 LLM tool specs 前检查一次指纹；同一会话后续 turn 不重复扫描。
- 只有各 Skill 根目录下的 `SKILL.md` 参与热加载指纹。新增、删除或修改 `SKILL.md` 会刷新 Skill registry；修改 `scripts/` 等辅助文件不会触发 prompt/tool spec 重建。
- `scripts/` 下的脚本由 `Bash` 等工具在执行时读取文件，因此脚本内容天然是最新版本，不需要把脚本文件纳入 prompt 热加载指纹。
- 已经运行中的 turn 使用启动时捕获的 prompt/tool snapshot，不会在执行过程中看到另一个新会话触发的 Skill 更新。

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增 Skill | 在本目录下创建 `<name>/SKILL.md`（无需改代码） |
| 修改内置 Skill 安装器说明 | [skill_installer/SKILL.md](skill_installer/SKILL.md) |
| frontmatter 解析与 Skill 名校验规则 | [metadata.py](metadata.py) — `parse_skill_metadata()` / `validate_skill_name()` |
| 扫描目录逻辑、工具 spec 生成 | [_loader.py](_loader.py) — `load_skills()` |
| 修改新会话热加载逻辑 | [hot_reload.py](hot_reload.py) — `SkillHotReloader` |

---

> 修改本目录或模块后，请同步更新此 README。
