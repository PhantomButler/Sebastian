---
version: "1.0"
last_updated: 2026-05-08
status: implemented
---

# Skill Package Manager

*← [Capabilities 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

Skill 包管理器为 Sebastian 提供第三方 Skill 的消费侧分发能力。它只实现
ClawHub-compatible registry consumer：用户可以搜索、检查、安装、更新和移除
Skill package；Sebastian 不实现 publish、sync、owner 管理或私有 registry auth。

## 用户入口

CLI 入口挂在 `sebastian skills`：

```bash
sebastian skills search "flight"
sebastian skills inspect flight-search
sebastian skills install flight-search
sebastian skills list
sebastian skills update flight-search
sebastian skills remove flight-search
```

默认 registry 为 `https://clawhub.ai`。`search`、`inspect`、`install` 按以下顺序解析
registry：

1. `--registry <url>`
2. `SEBASTIAN_SKILLS_REGISTRY_URL`
3. `https://clawhub.ai`

`update` 是特例：若未传 `--registry`，它使用该 Skill 安装时写入 lockfile 的
registry；显式传入 `--registry` 时才覆盖该记录。install/update/remove 等变更命令在
有效 registry 非默认值时要求确认，包括 update 使用的已存储 registry。

registry URL 必须是 HTTPS，且不能携带 query、fragment 或 credentials。CLI 使用
Python HTTP client 直连 registry，不 shell out 到 `clawhub` CLI。当前实现是 consumer
only，`update --all` 未开放，需按 slug 更新。

## 安装位置与运行时生命周期

安装目标是 `settings.skills_extensions_dir`，默认路径：

```text
~/.sebastian/data/extensions/skills
```

Gateway 启动时加载内置 Skill 与用户扩展 Skill；每个新 Sebastian session 的首轮
turn 会在组装 prompt/tool snapshot 前检查 `SKILL.md` 指纹。安装、更新或移除 Skill
后，变化对新 session 生效；已经运行中的 session 保持原有 snapshot。

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
- `GET /api/v1/download`

client 只解析 Sebastian 需要的字段：slug、name、description/summary、version、
download URL、sha256/digest 与 security/moderation status。下载 URL 必须是 HTTPS 且与
registry 同源；HTTP client 遵循标准 proxy 环境变量。

安装必须有 registry sha256。archive 下载后先校验 digest，再进入安全解压。被 registry
标记为 `malicious`、`quarantined`、`blocked`、`hidden`、`suspicious` 的 Skill
会 fail-closed。

zip archive 被视为不可信输入，安全扫描拒绝：

- 路径穿越、绝对路径、逃逸 staging root 的路径
- symlink、特殊文件、device、fifo、socket
- 超过 200 个文件
- 单文件超过 1 MiB
- 总解压体积超过 5 MiB
- 缺失根级或单一根目录下的 `SKILL.md`
- 非 UTF-8 或 frontmatter name 不合法的 `SKILL.md`

Skill name 解析复用 runtime loader 的 `parse_skill_metadata()` /
`validate_skill_name()`。runtime 注册名固定为 `skill__<frontmatter name>`；注册名冲突默认拒绝，
除非是同一 managed slug 的更新或显式 force reinstall。

## Install, Update, Remove

`install` 流程：

1. 解析 registry 与 Skill detail。
2. 校验 slug、security status、sha256。
3. 下载 archive 到临时目录并校验 digest。
4. 安全解压并解析 `SKILL.md` metadata。
5. 检查 registered name 冲突与 destination 状态。
6. 通过可恢复目录交换写入 `<skills_root>/<slug>`。
7. 写入 `.sebastian-origin.json`、计算 fingerprint、更新 lockfile。
8. 打印该 Skill 可用于新 Sebastian session。

`update` 只作用于 package-managed Skill。它会先比对本地 fingerprint；如果用户有本地
修改，默认拒绝，显式 `--force` 才会覆盖。若新版 `SKILL.md` 改变 runtime 注册名，默认拒绝，
显式 `--allow-rename` 才允许。模型辅助调用 CLI 时不得传 `--allow-rename`，除非用户在当前
对话中明确批准该 registered-name 变更。

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

## Builtin skill_installer

Sebastian 内置 `skill_installer` Skill，但没有新增 model-visible native
`install_skill` 工具。Agent-assisted install 使用既有 Bash 工具调用
`~/.sebastian/bin/sebastian skills ...`，保持模型可见工具面最小。

`skill_installer` 的安全流程：

- 先 search，再 inspect，安装或更新前必须检查候选 Skill。
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
