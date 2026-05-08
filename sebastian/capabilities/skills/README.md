# skills

> 上级索引：[capabilities/](../README.md)

## 目录职责

管理 Skill（复合能力）的动态加载与注册。Gateway 启动时会扫描本目录及用户自定义目录下的各 Skill 子目录，读取 `SKILL.md` 描述文件，将 Skill 包装为 `skill__<name>` 格式的工具并注入 `CapabilityRegistry`。新会话的首轮 turn 会在模型请求前检查 `SKILL.md` 指纹变化并刷新当前 Agent 的 prompt / tool snapshot，**无需修改核心代码或重启服务**即可让新会话看到新增或修改后的 Skill。

用户通过 `sebastian skills install` 安装的 package-managed Skill 默认落在
`~/.sebastian/data/extensions/skills`，与手工添加的用户 Skill 使用同一套
新会话热加载生命周期。默认 registry 是 `https://clawhub.ai`。search/inspect/install
使用显式 `--registry` → `SEBASTIAN_SKILLS_REGISTRY_URL` → 默认 registry 的顺序解析；
update 不传 `--registry` 时使用安装 lockfile 记录的 registry，显式传入
`--registry` 时覆盖该记录。install/update/remove 在有效 registry 非默认值时会确认，
包括 update 使用的已存储 registry。

## 目录结构

```
skills/
├── __init__.py        # 包入口（空）
├── _loader.py         # 扫描 SKILL.md、生成工具 spec
├── metadata.py        # 解析 SKILL.md frontmatter、校验 Skill 注册名
├── hot_reload.py      # 计算 SKILL.md 指纹，新会话首轮触发 Skill 热加载
└── skill_manager/     # 内置 Skill：通过 Sebastian CLI 管理 Skill
    └── SKILL.md
```

## Package Manager 生命周期

- `sebastian skills search <query>` / `inspect <slug>` 只读取 registry 元数据。
- `install <slug>` / `update <slug>` 会下载 registry zip；有 registry sha256 时校验，
  无 digest 时记录本地 archive SHA256，然后安全解压、写入 lockfile/origin metadata，
  并把 Skill 放入用户扩展目录。
- `list` 同时展示 builtin、package-managed 与本地 unmanaged Skill。
- `show <name-or-slug>` 读取本地 Skill metadata 与 `SKILL.md` instructions，不访问 registry。
- `remove <slug>` 只移除 package-managed Skill，并更新 lockfile。
- 安装、更新、移除后，变化对新的 Sebastian session 生效；当前运行中的 session
  继续使用已有 prompt/tool snapshot。

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
| 修改内置 Skill 管理器说明 | [skill_manager/SKILL.md](skill_manager/SKILL.md) |
| frontmatter 解析与 Skill 名校验规则 | [metadata.py](metadata.py) — `parse_skill_metadata()` / `validate_skill_name()` |
| 扫描目录逻辑、工具 spec 生成 | [_loader.py](_loader.py) — `load_skills()` |
| 修改新会话热加载逻辑 | [hot_reload.py](hot_reload.py) — `SkillHotReloader` |
| 修改 Skill package install/update/remove 实现 | ../../skills_registry/ 与 ../../cli/skills.py |

---

> 修改本目录或模块后，请同步更新此 README。
