---
name: integrate-spec
description: 将 docs/superpowers/specs/ 下的新 spec 文档整合进 docs/architecture/spec/ 结构化文档体系。包含交叉检查代码、判断归属、更新索引。
---

# integrate-spec - 整合 Spec 文档

将 `docs/superpowers/specs/` 下新写的 spec 文档整合进 `docs/architecture/spec/` 结构化文档体系。

## 使用方式

```
/integrate-spec
```

指定文件：`/integrate-spec docs/superpowers/specs/2026-04-12-xxx-design.md`

不指定时自动扫描 `docs/superpowers/specs/` 下所有未整合的文档（frontmatter 中无 `integrated_to` 字段的 `.md` 文件）。

## 文档体系概览

整合目标：`docs/architecture/spec/`

```
docs/architecture/spec/
├── INDEX.md              # 根索引（所有模块入口）
├── overview/             # 总体架构与 Agent 模型
├── core/                 # 核心运行时与基础设施
├── agents/               # Agent 系统与权限体系
├── capabilities/         # 能力体系（Tools/MCPs/Skills）
├── infra/                # 发布、CI/CD、部署
└── （可新建模块目录）
```

每个模块目录有 `INDEX.md`，根索引有模块一览表。

## 执行步骤

### 步骤 1：扫描待整合文档

```bash
# 找出所有未标记 integrated_to 的 spec
grep -rL "integrated_to:" docs/superpowers/specs/*.md 2>/dev/null
```

若无待整合文档，**终止**并提示。

列出待整合文档清单，让用户确认范围。

### 步骤 2：通读每篇新 spec

逐篇阅读，理解其核心内容和涉及的模块。

### 步骤 3：判断归属

对每篇新 spec，判断应该：

**A. 合并进现有 spec** — 内容是对已有 spec 的补充、修正或扩展（如给 core-tools.md 新增一个工具）

**B. 作为新文件加入现有模块** — 内容独立但属于已有模块范畴（如 agents/ 下新增一个 agent 的 spec）

**C. 新建模块目录** — 内容不属于任何现有模块（如首次出现的 `mobile/` 或 `gateway/` 模块）

判断依据：
- 读 `docs/architecture/spec/INDEX.md` 了解现有模块划分
- 读目标模块的 `INDEX.md` 了解已有 spec 覆盖范围
- 若新 spec 与某篇现有 spec 覆盖同一子系统（如都在讲 PolicyGate），选 A
- 若新 spec 是全新子系统但属于某模块（如新 agent），选 B
- 若根索引"待建模块"列表里有对应项，选 C

向用户展示判断结果和理由，等用户确认后再动手。

### 步骤 4：交叉检查代码实现

**这一步不可跳过。**

对照新 spec 的设计描述，检查实际代码：

1. spec 中提到的文件/类/函数是否存在
2. 接口签名、字段名、默认值是否与代码一致
3. spec 描述的流程是否与代码执行路径一致

使用 JetBrains PyCharm MCP 进行符号查询（若不可用则退回 Grep/Glob）。

记录发现的差异，分为：
- **实现增强**：代码比 spec 多做了（如防御性检查），在新 spec 中用 `> **实现增强**：...` 标注
- **实现差异**：代码与 spec 不同（如命名、默认值），在新 spec 中用 `> **实现差异**：...` 标注
- **未实现**：spec 描述的功能代码中不存在，将 `status` 设为 `in-progress` 或 `planned`

### 步骤 5：编写整合 spec

#### 方案 A：合并进现有 spec

1. 读取现有 spec 全文
2. 将新内容融入对应章节，或新增章节
3. 更新 frontmatter：`last_updated` 改为今天，`version` 递增小版本
4. 注意不要破坏现有内容的准确性

#### 方案 B：新建 spec 文件

文件放在对应模块目录下，命名用小写短横线连接（如 `stock-agent.md`）。

必须包含：

```yaml
---
version: "1.0"
last_updated: YYYY-MM-DD
status: implemented | in-progress | planned
---
```

文件首尾的导航链接格式（**只做父索引链接，不做兄弟 prev/next**）：

```markdown
# 标题

*← [模块名 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

（正文）

---

*← [模块名 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
```

#### 方案 C：新建模块目录

1. 创建 `docs/architecture/spec/{module}/` 目录
2. 创建 `INDEX.md`（参考现有模块索引格式）
3. 创建 spec 文件（同方案 B）

INDEX.md 格式：

```markdown
# {模块名} Spec 索引

*← [Spec 根索引](../INDEX.md)*

---

{一句话模块描述}

| Spec | 摘要 |
|------|------|
| [xxx.md](xxx.md) | 一行摘要 |

---

*← [Spec 根索引](../INDEX.md)*
```

### 步骤 6：更新索引

**所有方案都必须执行此步骤。**

1. **模块 INDEX.md**：更新 spec 表格（新增行或更新摘要）
2. **根 INDEX.md**：
   - 方案 A/B：更新对应模块的 spec 表格
   - 方案 C：新增模块段落，从"待建模块"表中移除对应行

### 步骤 7：标记原始文档已整合

在原始 spec 文件（`docs/superpowers/specs/` 下）的 frontmatter 中**追加**字段：

```yaml
integrated_to: agents/permission.md    # 整合目标路径（相对于 docs/architecture/spec/）
integrated_at: 2026-04-12              # 整合日期
```

若原文件没有 frontmatter，在文件开头添加：

```yaml
---
integrated_to: agents/permission.md
integrated_at: 2026-04-12
---
```

**不改文件名，不移动文件。** frontmatter 标记足以识别状态。

### 步骤 8：输出结果

```
✓ 整合完成

已处理：
- docs/superpowers/specs/2026-04-12-xxx.md
  → 合并进 docs/architecture/spec/agents/permission.md（方案 A）
  → 代码交叉检查：2 处实现差异已标注

索引已更新：
- docs/architecture/spec/agents/INDEX.md
- docs/architecture/spec/INDEX.md

提交请运行 /commit-pr
```

## 规范速查

### Frontmatter

```yaml
version: "1.0"           # 内容实质变更时递增
last_updated: 2026-04-10 # 每次变更时更新
status: implemented | in-progress | planned
```

### 链接格式

- **只做父索引链接**，不做兄弟 prev/next
- 文件首尾各一行：`*← [模块名 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*`

### 命名

- 模块目录：小写英文（`agents/`、`capabilities/`）
- Spec 文件：小写短横线（`code-agent.md`、`core-tools.md`）
- 与代码模块名对齐，不用日期前缀

### 内容风格

- 中文为主，代码/术语保留英文
- 用代码块展示接口和数据结构
- 差异标注用 blockquote：`> **实现差异**：...`
- "不在本 spec 范围内"章节明确边界
