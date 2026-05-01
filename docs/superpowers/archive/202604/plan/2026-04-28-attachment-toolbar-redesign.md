# Attachment Toolbar Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将附件按钮的二级下拉菜单改为文件和图片两个并排直接触发的图标按钮。

**Architecture:** 重写 `AttachmentSlot.kt`（改名为 `AttachmentToolbar`，去掉 DropdownMenu，新增第二个 IconButton），更新 `ChatScreen.kt` 中的 import 和插槽 lambda。`Composer.kt` 插槽 API 不变。

**Tech Stack:** Kotlin, Jetpack Compose, Material3 Icons

---

## File Map

| 文件 | 操作 |
|------|------|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentSlot.kt` | 重写 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` | 修改（import + slot lambda） |

> 注：`Composer.kt` 和 ViewModel / 测试文件均不需要改动。

---

## Task 1: 重写 AttachmentSlot.kt 为 AttachmentToolbar

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentSlot.kt`

- [ ] **Step 1: 将文件完整替换为以下内容**

```kotlin
package com.sebastian.android.ui.composer

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Row
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Image
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.graphics.Color

@Composable
fun AttachmentToolbar(
    onFileClick: () -> Unit,
    onImageClick: () -> Unit,
    enabled: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val iconTint = if (isSystemInDarkTheme()) Color(0xFF9E9E9E) else Color.Black

    Row(modifier) {
        IconButton(
            onClick = onFileClick,
            enabled = enabled,
            modifier = Modifier.focusProperties { canFocus = false },
        ) {
            Icon(Icons.Default.AttachFile, contentDescription = "选择文件", tint = iconTint)
        }
        IconButton(
            onClick = onImageClick,
            enabled = enabled,
            modifier = Modifier.focusProperties { canFocus = false },
        ) {
            Icon(Icons.Default.Image, contentDescription = "选择图片", tint = iconTint)
        }
    }
}
```

> 注意：
> - 容器从 `Box` 改为 `Row`，两个按钮水平排列
> - 删除了 `expanded` state、`DropdownMenu`、`DropdownMenuItem` 及相关 import
> - `focusProperties { canFocus = false }` 保证点击不收起键盘（与之前修复一致）
> - 夜间模式 `iconTint` 两个按钮共用

---

## Task 2: 更新 ChatScreen.kt

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`

- [ ] **Step 1: 更新 import**

将：
```kotlin
import com.sebastian.android.ui.composer.AttachmentSlot
```
改为：
```kotlin
import com.sebastian.android.ui.composer.AttachmentToolbar
```

- [ ] **Step 2: 更新 attachmentSlot lambda（位于 ChatScreen.kt 约第 416 行）**

将：
```kotlin
attachmentSlot = {
    AttachmentSlot(
        onImageClick = chatViewModel::onAttachmentMenuImageSelected,
        onFileClick = {
            filePickerLauncher.launch(
                arrayOf("text/plain", "text/markdown", "text/csv", "application/json", "text/x-log")
            )
        },
        enabled = chatState.composerState == ComposerState.IDLE_EMPTY
            || chatState.composerState == ComposerState.IDLE_READY,
    )
},
```
改为：
```kotlin
attachmentSlot = {
    AttachmentToolbar(
        onFileClick = {
            filePickerLauncher.launch(
                arrayOf("text/plain", "text/markdown", "text/csv", "application/json", "text/x-log")
            )
        },
        onImageClick = {
            imagePickerLauncher.launch(
                PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
            )
        },
        enabled = chatState.composerState == ComposerState.IDLE_EMPTY
            || chatState.composerState == ComposerState.IDLE_READY,
    )
},
```

> 注意：`onImageClick` 直接 launch picker，不再经过 `chatViewModel.onAttachmentMenuImageSelected`，这是等价的最短路径（原方法唯一作用是触发 `RequestImagePicker` effect 再回来 launch）。

---

## Task 3: 编译验证并提交

**Files:** 以上两个文件

- [ ] **Step 1: 编译验证**

```bash
cd ui/mobile-android
./gradlew assembleDebug 2>&1 | tail -20
```

期望输出以 `BUILD SUCCESSFUL` 结尾，无编译错误。

如果报错 `Unresolved reference: AttachmentSlot`，检查 `ChatScreen.kt` import 是否已正确替换。

- [ ] **Step 2: 提交**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentSlot.kt
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
git commit -m "feat(composer): 附件工具栏改版，去掉二级菜单改为双图标直触

文件按钮直接打开文件选择器，图片按钮直接打开图片选择器。
AttachmentSlot 重写为 AttachmentToolbar，Composer 插槽 API 不变。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
