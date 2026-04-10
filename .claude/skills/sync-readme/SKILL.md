---
name: sync-readme
description: 扫描仓库目录，检测缺失、过时或与代码不匹配的 README，按规范批量更新并维护索引链接一致性。
---

# sync-readme - 扫描并更新仓库 README

自动扫描后端 `sebastian/` 与前端 `ui/mobile/` 目录树，检测缺失、过时或与代码不匹配的 README，按规范更新并保持索引链接一致性。

## 使用方式

```
/sync-readme
```

指定范围：`/sync-readme sebastian/core` 或 `/sync-readme ui/mobile`

不指定时扫描全量目录。

## 执行步骤

### 步骤 1：收集目录与 README 清单

扫描以下根目录的所有子目录（排除 `__pycache__/`、`node_modules/`、`.venv/`）：

- `sebastian/`（后端）
- `ui/mobile/`（前端，排除 `node_modules/`）

产出两个列表：
- **有 README 的目录**
- **无 README 的目录**

> 仅扫描包含 `.py` / `.ts` / `.tsx` 源码文件或已有 README 的目录。纯资源目录（如 `assets/`）、生成目录（如 `android/`、`ios/`）不需要 README。

### 步骤 2：检测缺失的 README

对每个无 README 的目录，判断是否需要新建：

| 条件 | 是否需要 README |
|------|----------------|
| 含 2+ 个源码文件，且有独立模块职责 | 需要 |
| 仅 `__init__.py` 一个文件（纯包标记） | 不需要 |
| 已有上级 README 充分覆盖其内容 | 不需要 |
| 含子目录且子目录有 README | 需要（作为索引） |

列出需要新建 README 的目录清单，让用户确认。

### 步骤 3：检测过时的 README

对每个已有 README 的目录，执行以下检查：

#### 3a. 目录树一致性

对比 README 中列出的文件/子目录与实际目录内容：
- README 提到但实际不存在的文件 → **标记：已删除**
- 实际存在但 README 未提及的文件 → **标记：未收录**

> 检查范围：README 中的「目录结构」代码块和「模块说明」段落中提到的文件名。

#### 3b. 代码实现匹配

对 README 中提到的关键代码元素，使用 JetBrains PyCharm MCP（不可用时退回 Grep）验证：
- 类名 / 函数名是否仍存在
- 文件路径是否正确
- 模块职责描述是否与当前代码一致

重点关注：
- 函数/类被重命名或删除
- 文件被移动到其他目录
- 模块职责发生变化（如从占位变为实现）

#### 3c. 占位 README 升级检测

检查标记为 Phase N 占位的 README（如 identity/、trigger/、sandbox/）：
- 若目录中实际源码超出占位描述的范围，提醒需要升级为完整 README
- 若仍为占位状态，保持不动

#### 3d. 索引链接完整性

检查父子 README 之间的双向链接：
- 子 README 的「上级」链接是否指向正确的父 README
- 父 README 的目录树/索引表是否包含所有有 README 的子目录
- 链接路径是否正确（相对路径）

### 步骤 4：生成审计报告

向用户展示结构化报告：

```
README 审计报告

缺失（需新建）：
- sebastian/xxx/  — 原因

过时（需更新）：
- sebastian/yyy/README.md
  - [已删除] old_file.py 已不存在
  - [未收录] new_file.py 未出现在 README 中
  - [重命名] OldClass → NewClass

占位升级：
- sebastian/zzz/README.md — 已有实际实现，建议升级

索引断链：
- sebastian/README.md 缺少 → xxx/ 的链接
- sebastian/xxx/README.md 上级链接路径错误

无需更新：
- sebastian/core/README.md ✓
- ...
```

**等用户确认范围后再动手。**

### 步骤 5：执行更新

#### 新建 README

遵循现有 README 风格规范：

```markdown
# {模块名} 模块

> 上级：[{父模块}/README.md]({相对路径})

{一句话模块定位}

## 目录结构

{实际文件树}

## 模块说明

{每个关键文件的职责说明}

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| ... | ... |

---

> 修改模块结构后，请同步更新本 README。
```

编写前**必须先读对应目录的所有源码文件**，确保描述准确。

#### 更新已有 README

- 补充未收录的文件
- 移除已删除的文件引用
- 修正重命名/移动的代码元素
- 更新模块职责描述（若有变化）
- 升级占位 README（补充实际实现描述）

**只改有问题的部分，不重写正确的内容。**

#### 修复索引链接

- 父 README 的目录树：补充缺失的子目录链接
- 子 README 的上级链接：修正路径
- 修改导航表：补充新增模块对应的行

### 步骤 6：最终一致性验证

更新完成后，对所有修改过的 README 做一轮快速验证：

1. 每个 README 中的「目录结构」代码块与实际目录 `ls` 结果一致
2. 父子 README 双向链接完整且路径正确
3. 根 README（`sebastian/README.md` 或 `ui/mobile/README.md`）的目录树包含所有子模块

### 步骤 7：输出结果

```
✓ README 同步完成

新建：
- sebastian/xxx/README.md

更新：
- sebastian/yyy/README.md（+2 文件，-1 已删除引用）
- sebastian/README.md（索引表 +1 行）

无需变更：12 个 README

提交请运行 /commit-pr
```

## README 规范速查

### 文件结构

```markdown
# {模块名} 模块（或 {模块名} Guide）

> 上级：[{parent}/README.md]({path})

{一句话定位}

## 目录结构
## 模块说明
## 修改导航

---
> 维护提示
```

### 命名与风格

- 标题：后端用「模块」，前端/顶层用英文名或「Guide」
- 语言：中文为主，代码术语保留英文
- 上级链接：每个子 README 开头必须有
- 修改导航表：`| 修改场景 | 优先看 |` 格式
- 维护提示：文末分隔线后一行 blockquote

### 不需要 README 的目录

- `__pycache__/`、`node_modules/`、`.venv/` — 生成/依赖目录
- `android/`、`ios/` — Expo 管理的原生工程
- `assets/` — 纯静态资源
- 仅含 `__init__.py` 的纯包标记目录
