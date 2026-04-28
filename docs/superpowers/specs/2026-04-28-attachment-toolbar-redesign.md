# Attachment Toolbar Redesign

**Date:** 2026-04-28  
**Status:** Approved

## Background

当前 `AttachmentSlot` 组件通过一个 `IconButton` + `DropdownMenu` 提供图片和文件两种附件选择，用户需要两次点击才能打开选择器。目标是去掉二级菜单，将两个选择器入口直接展示为工具栏中并排的两个图标按钮。

## Goal

- 附件按钮（文件图标）点击直接打开文件选择器
- 新增图片按钮（图片图标）点击直接打开图片选择器，位于文件按钮右侧
- 两个按钮夜间模式颜色适配保持与现有修复一致
- 点击任意按钮不收起键盘（`focusProperties { canFocus = false }`）

## Changes

### `ui/composer/AttachmentSlot.kt`

- 组件改名：`AttachmentSlot` → `AttachmentToolbar`
- 签名：`(onFileClick: () -> Unit, onImageClick: () -> Unit, enabled: Boolean, modifier: Modifier)`
- 删除：`expanded` state、`DropdownMenu`、`DropdownMenuItem`
- 新增：两个并排 `IconButton`
  - 左：`Icons.Default.AttachFile`，`onClick = onFileClick`
  - 右：`Icons.Default.Image`，`onClick = onImageClick`
- 两个 `IconButton` 均加 `Modifier.focusProperties { canFocus = false }`
- 夜间颜色：`if (isSystemInDarkTheme()) Color(0xFF9E9E9E) else Color.Black`（两个图标共用同一 `iconTint`）

### `ui/chat/ChatScreen.kt`

- import 从 `AttachmentSlot` 改为 `AttachmentToolbar`
- `attachmentSlot` lambda 内改为：
  ```kotlin
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
  ```
- `onImageClick` 直接 launch picker，不经过 `chatViewModel.onAttachmentMenuImageSelected`（该方法原职责就是触发 `RequestImagePicker` effect 再回来 launch，直接 launch 是等价最短路径）

### `ui/composer/Composer.kt`

- 无需改动，插槽参数 `attachmentSlot: @Composable (() -> Unit)?` 签名不变

## Not In Scope

- `chatViewModel.onAttachmentMenuImageSelected` 及 `ChatUiEffect.RequestImagePicker` 不删除，其他地方可能仍然使用（留给后续清理）
- `AttachmentSlot` 旧名的兼容 export 不做，直接重命名，一次性改干净

## File Impact

| 文件 | 变更类型 |
|------|---------|
| `ui/composer/AttachmentSlot.kt` | 重写（改名 + 去掉 Dropdown + 新增第二按钮） |
| `ui/chat/ChatScreen.kt` | 更新 import + 更新 slot lambda |
| `ui/composer/Composer.kt` | 不变 |
