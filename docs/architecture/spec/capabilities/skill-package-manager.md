---
version: "1.2"
last_updated: 2026-05-09
status: implemented
---

# Skill Package Manager

*← [Capabilities 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

Skill 包管理器为 Sebastian 提供第三方 Skill 的消费侧分发能力，并承载当前 Skill
runtime 的 progressive disclosure 模型。Sebastian 只实现 ClawHub-compatible registry
consumer：用户可以搜索、检查、安装、更新和移除 Skill package；Sebastian 不实现
publish、sync、owner 管理或私有 registry auth。

Skill 是本地 catalog package，不是 LLM provider tool。模型默认只看到一段短的 Skill
Management bootstrap；需要使用 Skill 时，通过既有 `Bash` 工具调用 `sebastian skills
list/search/show/read` 按需读取本地 Skill 内容。这个模型取代了早期
`skill__<name>` provider tool 与新 session 热重载工具 spec 的设计。

## 用户入口

CLI 入口挂在 `sebastian skills`：

```bash
sebastian skills search "flight"
sebastian skills search "flight" --source registry
sebastian skills inspect flight-search
sebastian skills install flight-search
sebastian skills list
sebastian skills show flight-search
sebastian skills show flight-search --body
sebastian skills read flight-search references/usage.md
sebastian skills update flight-search
sebastian skills remove flight-search
```

`search` 默认只搜索本地已安装 Skill。它把本地查询按空白分词，过滤 ASCII 停用词，
再用 OR 语义匹配 slug、frontmatter `name`、兼容 `registered_name` 与 description。
短的精确 Skill name/slug 会被保留，不会因为短词或停用词规则被丢弃。结果按确定性
score 排序，并用 source、slug 等稳定字段打破并列。搜索不会生成或写入 Skill
metadata；本阶段不新增检索词字段、别名字段或安装时包内容改写。

只有 `--source registry` 或 `--source all` 才访问远端 registry；单独传 `--registry`
不会触发网络访问。默认 registry 为 `https://clawhub.ai`。远端 `search`、`inspect`、
`install` 按以下顺序解析 registry：

1. `--registry <url>`
2. `SEBASTIAN_SKILLS_REGISTRY_URL`
3. `https://clawhub.ai`

`update` 是特例：若未传 `--registry`，它使用该 Skill 安装时写入 lockfile 的
registry；显式传入 `--registry` 时才覆盖该记录。install/update/remove 等变更命令在
有效 registry 非默认值时要求确认，包括 update 使用的已存储 registry。

registry URL 必须是 HTTPS，且不能携带 query、fragment 或 credentials。CLI 使用
Python HTTP client 直连 registry，不 shell out 到 `clawhub` CLI。当前实现是 consumer
only；`update --all` 会遍历 package-managed Skill，跳过 unmanaged Skill，单个失败不影响后续更新。

本地 Skill lookup 只针对本机 catalog，匹配顺序为 slug、frontmatter `name`、兼容
`registered_name`。`skill__<name>` 输入可作为兼容别名解析，但它不再表示可调用工具名。
如果多个本地 Skill 匹配同一 identifier，命令必须失败并列出候选 slug，不自动猜测。

## Progressive Disclosure Runtime

运行时边界：

- Native tools 与 MCP tools 仍是唯一 provider tool 来源，受 `allowed_tools`、PolicyGate
  与 PermissionReviewer 约束。
- Skill 不进入 `CapabilityRegistry`、不进入 provider tool specs、不通过
  `allowed_skills` 控制执行权限。
- `allowed_skills` manifest 字段已废弃；Agent loader 看到该字段会 fail-fast，提示
  Skill 访问应通过 `Bash` + `sebastian skills` CLI。
- Agent 若没有 `Bash`，就不能通过 CLI 使用 Skill。这是有意设计：Skill 访问留在既有
  executable tool permission chain 内，不新增第二套 Skill ACL。

默认 system prompt 只注入固定短 bootstrap，提示模型使用：

```bash
sebastian skills list
sebastian skills search <query>
sebastian skills show <name-or-slug>
sebastian skills show <name-or-slug> --body
sebastian skills read <name-or-slug> <relative-path>
sebastian skills inspect/install/update/remove ...
```

本地 Skill 内容以磁盘当前文件为准；`show --body` 和 `read` 在命令执行时读取文件，不依赖
gateway 中的 runtime snapshot。Registry search/inspect 只用于远端发现和安装前检查，不是
已安装 Skill 的权威使用说明。

## 本地 Catalog 读取

`list` 同时列出 builtin、package-managed 与 unmanaged Skill。

`show <name-or-slug>` 默认输出 metadata、路径、来源、managed/version/registry 信息与文件列表，
不打印完整 `SKILL.md` 正文；`--body` 才输出本地 `SKILL.md` body。

`read <name-or-slug> <relative-path>` 只读取目标 Skill 目录内的 UTF-8 文本文件，用于按需查看
`references/`、`scripts/`、`assets/` 等辅助文件。安全规则：

- 只接受相对路径，拒绝绝对路径、空路径、`.`、`..` 与任何包含 `..` 的路径。
- 解析后的目标必须仍位于 Skill root 内，拒绝 symlink escape。
- 拒绝隐藏路径、manager-owned metadata、目录和特殊文件。
- 拒绝二进制或非 UTF-8 内容。
- `show --body` 与 `read` 的初始输出上限为 128 KiB，超过则失败，要求用户读取更小文件。

文件列表默认排除隐藏文件、隐藏目录和 manager-owned metadata，并按字典序排序；symlink 可以标记为
symlink，但 listing 不跟随 symlink。

## 安装位置与 Catalog Watcher

安装目标是 `settings.skills_extensions_dir`，默认路径：

```text
~/.sebastian/data/extensions/skills
```

Gateway 启动时只记录内置 Skill 与用户扩展 Skill 的 `SKILL.md` 指纹；Skill 不作为
provider tool 暴露，也不默认注入 prompt。安装、更新或移除 Skill 后，本地 catalog
读取以磁盘当前文件为准；模型需要说明时通过 `sebastian skills show --body` 或
`sebastian skills read` 按需读取。

`SkillHotReloader` 在当前实现中是轻量 catalog watcher：它只计算各 Skill 根目录下
`SKILL.md` 的 `mtime_ns + size` 指纹并维护单调 version。它不注册、替换或删除 provider
tool specs，也不触发 per-agent prompt rebuild。修改 `scripts/`、`references/` 等辅助文件不会
改变 watcher version；这些文件由 CLI 在使用时直接读取，因此天然反映磁盘最新内容。

## Package Metadata

package-managed Skill 使用两层 metadata：

```text
~/.sebastian/data/extensions/skills/.sebastian-skills.lock.json
~/.sebastian/data/extensions/skills/<slug>/.sebastian-origin.json
```

lockfile 记录 slug、runtime 注册名、registry、version、tag、sha256、fingerprint 与
installed_at。origin 文件复制单个 Skill 的来源信息，便于人工检查和 lockfile 损坏时恢复。

lockfile 写入使用 POSIX `fcntl.flock` 串行化；JSON 写入采用同目录临时文件、flush、
fsync、atomic replace，并 fsync 父目录。目录替换与 lockfile/origin 写入组成可恢复事务：
若 metadata 写入失败，会回滚到替换前的 Skill 目录。

fingerprint 排除 manager-owned metadata，包括 `.sebastian-origin.json` 与
`.sebastian/`，避免安装器写入自身 metadata 后立即制造本地修改。

## Registry 与下载安全

registry client 读取 ClawHub-compatible endpoint：

- `GET /api/v1/search?q=<query>&limit=<n>`
- `GET /api/v1/skills/<slug>`
- `GET /api/v1/download?slug=<slug>[&version=<version>]`

client 只解析 Sebastian 需要的字段：slug、name/displayName、description/summary、
version、download URL、sha256/digest 与 security/moderation status。search 兼容
`items` 与 ClawHub `results`；inspect 兼容扁平 detail 与 ClawHub
`skill` / `latestVersion` / `moderation` 包装层。若 detail 未提供 direct download URL，
client 使用同源 `/api/v1/download` fallback，并携带 slug/version 查询参数。
当用户显式请求 `--version` 而 registry detail 未回显 version 时，fallback URL 仍使用该
requested version，避免误下载默认版本。
direct 下载 URL 必须是 HTTPS 且与 registry 同源；HTTP client 遵循标准 proxy 环境变量。

registry sha256/digest 是可选字段。若 registry 提供 digest，archive 下载后必须匹配；
若未提供，Sebastian 会计算本地 zip SHA256、写入 lockfile/origin metadata，并记录
未经过 registry digest 预校验的 warning。被 registry 标记为 `malicious`、
`quarantined`、`blocked`、`hidden`、`suspicious` 的 Skill 会 fail-closed。

zip archive 被视为不可信输入，安全扫描拒绝：

- 路径穿越、绝对路径、逃逸 staging root 的路径
- symlink、特殊文件、device、fifo、socket
- 超过 200 个文件
- 单文件超过 1 MiB
- 总解压体积超过 5 MiB
- 缺失根级或单一根目录下的 `SKILL.md`
- 非 UTF-8 或 frontmatter name 不合法的 `SKILL.md`

Skill name 解析复用 metadata loader 的 `parse_skill_metadata()` /
`validate_skill_name()`。兼容 registered name 固定为 `skill__<frontmatter name>`；注册名冲突默认拒绝，
除非是同一 managed slug 的更新或显式 force reinstall。

## Install, Update, Remove

`install` 流程：

1. 解析 registry 与 Skill detail。
2. 校验 slug 与 security status。
3. 下载 archive 到临时目录；有 registry digest 时校验 digest，否则记录本地 archive SHA256。
4. 安全解压并解析 `SKILL.md` metadata。
5. 检查 registered name 冲突与 destination 状态。
6. 通过可恢复目录交换写入 `<skills_root>/<slug>`。
7. 写入 `.sebastian-origin.json`、计算 fingerprint、更新 lockfile。
8. 打印该 Skill 可用于新 Sebastian session。

`update` 只作用于 package-managed Skill。它会先比对本地 fingerprint；如果用户有本地
修改，默认拒绝，显式 `--force` 才会覆盖。若新版 `SKILL.md` 改变 runtime 注册名，默认拒绝，
显式 `--allow-rename` 才允许。模型辅助调用 CLI 时不得传 `--allow-rename`，除非用户在当前
对话中明确批准该 registered-name 变更。
本地 fingerprint 通过后，若 registry 解析出的 version 与 lockfile 中已安装 version
相同且未传 `--force`，`update` 直接 no-op，不下载或重写本地目录。

`remove` 只移除 package-managed Skill。交互式 CLI 默认要求确认；命令执行时删除目录并移除
lockfile entry。已有 session 不受影响，新 session 不再看到该 Skill。

## PATH Shim

安装与升级流程创建稳定入口：

```text
~/.sebastian/bin/sebastian
```

shim 转发到安装目录内的 `.venv/bin/sebastian`。`SEBASTIAN_INSTALL_DIR` 自定义时，
shim target 指向解析后的安装目录；默认用户安装的 shim 路径保持固定。

除非设置 `SEBASTIAN_SKIP_PATH_SETUP=1`，安装器会在支持的 zsh/bash rc 文件写入幂等 block：

```sh
# >>> sebastian PATH >>>
export PATH="$HOME/.sebastian/bin:$PATH"
# <<< sebastian PATH <<<
```

跳过 PATH 设置只跳过 shell rc 写入，不跳过 shim 创建。`sebastian update` 成功后也刷新
shim，保证旧版本升级后拥有稳定 CLI 入口。

## Builtin skill_manager

Sebastian 内置 `skill_manager` Skill，但没有新增 model-visible native
`install_skill` 或 `read_skill` 工具。`skill_manager` 本身也是本地 catalog package，
不会作为 `skill__skill_manager` provider tool 暴露；模型需要它的完整规则时，通过
`sebastian skills show skill_manager --body` 读取。Agent-assisted Skill 管理使用既有 Bash
工具调用 PATH 中的公共 `sebastian skills ...` CLI，保持模型可见工具面最小。Skill
不直接调用安装态 shim 路径；实际目标数据目录由运行环境中的 `SEBASTIAN_DATA_DIR` 决定。

`skill_manager` 的安全流程：

- 本地 Skill 使用问题先 `list`，再 `show`；本地 `show` 内容是实际使用说明的权威来源。
- 远端安装/更新先 search，再 inspect，安装或更新前必须检查候选 Skill。
- 安装/更新确认前，向用户总结 registry inspect 可见信息：slug、name、version、
  security status、download URL 与 SHA256，以及 warnings。registered runtime name 需要下载并解析
  `SKILL.md` 后才能确定，因此由 install/update 成功输出报告。CLI inspect 当前不列 bundle
  文件，除非未来 registry metadata 提供，否则不要求文件列表摘要。
- install/update/remove 前必须获得当前对话中的显式确认。
- 不自动使用 `--yes`、`--force`、`--allow-rename` 或非默认 `--registry`；只有用户在当前
  对话中明确批准 registered-name 变更时，模型才可传 `--allow-rename`。
- 不通过 `--force` 绕过 unsafe registry status。
- 不运行下载包中的脚本，不使用 `curl | bash` 第三方安装流。
- 完成后告知用户变更只对新的 Sebastian session 生效。

---

*← [Capabilities 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
