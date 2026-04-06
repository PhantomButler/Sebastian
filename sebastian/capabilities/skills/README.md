# skills

> 上级索引：[capabilities/](../README.md)

## 目录职责

管理 Skill（复合能力）的动态加载与注册。启动时自动扫描本目录及用户自定义目录下的各 Skill 子目录，读取 `SKILL.md` 描述文件，将 Skill 包装为 `skill__<name>` 格式的工具并注入 `CapabilityRegistry`，**无需修改任何核心代码**即可扩展新能力。

## 目录结构

```
skills/
├── __init__.py        # 包入口（空）
└── _loader.py         # 扫描 SKILL.md、解析 frontmatter、生成工具 spec
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
- 工具名统一前缀为 `skill__<name>`
- 后加载的目录可覆盖同名 Skill（支持用户自定义覆盖内置 Skill）
- 目录名以 `_` 开头的子目录跳过（如 `_loader.py` 所在位置）

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增 Skill | 在本目录下创建 `<name>/SKILL.md`（无需改代码） |
| frontmatter 解析规则 | [_loader.py](_loader.py) — `_parse_frontmatter()` |
| 扫描目录逻辑、工具 spec 生成 | [_loader.py](_loader.py) — `load_skills()` |

---

> 修改本目录或模块后，请同步更新此 README。
