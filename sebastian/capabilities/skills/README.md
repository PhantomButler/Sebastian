# skills

> 上级索引：[capabilities/](../README.md)

## 目录职责

管理 Skill（复合能力）的本地 catalog。Skill 不再包装为 `skill__<name>` provider tool，也不注入 `CapabilityRegistry` 或系统 prompt；模型只通过 `Bash` 调用 `sebastian skills list/search/show/read` 按需发现和读取本地 Skill 内容。Gateway 启动时只记录 `SKILL.md` 指纹，用于观测本地 catalog 变化。

用户通过 `sebastian skills install` 安装的 package-managed Skill 默认落在
`~/.sebastian/data/extensions/skills`，与手工添加的用户 Skill 一起组成本地 catalog。
`sebastian skills search` 默认只搜本地；只有 `--source registry` 或 `--source all`
才访问远端 registry。默认 registry 是 `https://clawhub.ai`。remote search/inspect/install
使用显式 `--registry` → `SEBASTIAN_SKILLS_REGISTRY_URL` → 默认 registry 的顺序解析；
update 不传 `--registry` 时使用安装 lockfile 记录的 registry，显式传入
`--registry` 时覆盖该记录。install/update/remove 在有效 registry 非默认值时会确认，
包括 update 使用的已存储 registry。

## 目录结构

```
skills/
├── __init__.py        # 包入口（空）
├── _loader.py         # 扫描 SKILL.md、生成 catalog metadata
├── metadata.py        # 解析 SKILL.md frontmatter、校验 Skill 注册名
├── hot_reload.py      # 计算 SKILL.md 指纹与 catalog 版本
└── skill_manager/     # 内置 Skill：通过 Sebastian CLI 管理 Skill
    └── SKILL.md
```

## Package Manager 生命周期

- `sebastian skills search <query>` 默认只读取本地 catalog；`inspect <slug>` 读取 registry 元数据。
- `install <slug>` / `update <slug>` 会下载 registry zip；有 registry sha256 时校验，
  无 digest 时记录本地 archive SHA256，然后安全解压、写入 lockfile/origin metadata，
  并把 Skill 放入用户扩展目录。
- `list` 同时展示 builtin、package-managed 与本地 unmanaged Skill。
- `show <name-or-slug>` 默认读取本地 Skill metadata、路径和文件列表，不访问 registry；`--body` 才输出 `SKILL.md` 正文。
- `read <name-or-slug> <relative-path>` 只读目标 Skill 目录内可见文件，拒绝隐藏/manager metadata、绝对路径、`..` 和 symlink escape。
- `remove <slug>` 只移除 package-managed Skill，并更新 lockfile。
- 安装、更新、移除后，CLI 读取到的本地 Skill 内容以磁盘当前文件为准。

内置 `skill_manager` Skill 负责安全的 agent-assisted Skill management flow：它会使用
PATH 中的公共 `sebastian skills ...` CLI 列出和读取本地 Skill，也会搜索和检查 registry
Skill，安装/更新确认前向用户总结
inspect 可见的 registry metadata（registry、slug/name、version、安全/审核状态、
download/SHA 信息和警告），并在用户确认后才执行 install/update/remove。runtime
注册名只能在下载并解析 `SKILL.md` 后确定，因此由 install/update 成功后的 CLI 输出报告。
CLI inspect 当前不列 bundle 文件，除非未来 registry metadata 提供，否则不要求总结文件列表。
该 Skill 不会运行下载包中的脚本，不使用 `curl | bash`，也不会自动使用 `--force`、
`--yes`、`--allow-rename` 或非默认 registry；它不直接调用安装态 shim 路径，目标数据目录由
运行环境中的 `SEBASTIAN_DATA_DIR` 决定。

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

详细的调用指导。该正文不会默认注入 LLM，需要时通过 `sebastian skills show <name-or-slug> --body` 读取。
```

加载规则：
- `name` 只能包含英文字母、数字、下划线和短横线，不能包含路径分隔、空格或点号
- `name` 必须写裸 Skill 名，不能包含 `skill__` 前缀
- 兼容注册名为 `skill__<name>`，但它只是 catalog metadata，不是可调用工具
- 后加载的目录可覆盖同名 Skill（支持用户自定义覆盖内置 Skill）
- 目录名以 `_` 开头的子目录跳过（如 `_loader.py` 所在位置）
- 不合法的 Skill 会被跳过并记录 warning

## Catalog 指纹生命周期

- Gateway 启动时记录当前 `SKILL.md` 指纹。
- 只有各 Skill 根目录下的 `SKILL.md` 参与指纹。新增、删除或修改 `SKILL.md` 会更新 catalog watcher 版本；修改 `scripts/` 等辅助文件不会触发版本变化。
- `scripts/`、`references/` 等辅助文件由 `sebastian skills read` 或 `Bash` 在执行时读取，因此内容天然以磁盘当前文件为准。

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增 Skill | 在本目录下创建 `<name>/SKILL.md`（无需改代码） |
| 修改内置 Skill 管理器说明 | [skill_manager/SKILL.md](skill_manager/SKILL.md) |
| frontmatter 解析与 Skill 名校验规则 | [metadata.py](metadata.py) — `parse_skill_metadata()` / `validate_skill_name()` |
| 扫描目录逻辑、catalog metadata 生成 | [_loader.py](_loader.py) — `load_skill_catalog()` |
| 修改 Skill catalog 指纹逻辑 | [hot_reload.py](hot_reload.py) — `SkillHotReloader` |
| 修改 Skill package install/update/remove 实现 | ../../skills_registry/ 与 ../../cli/skills.py |

---

> 修改本目录或模块后，请同步更新此 README。
