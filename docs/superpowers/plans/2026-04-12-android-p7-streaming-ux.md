# Android P7 Streaming UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three streaming UX improvements from spec: (1) Markdown parsing on IO thread instead of Main thread; (2) 50ms delta debounce to reduce recomposition pressure; (3) "回到底部" FAB when user has scrolled away.

**Architecture:**
- Markdown: `TextBlock` gains `renderedMarkdown: CharSequence?`; `ChatViewModel.handleEvent(TextBlockStop)` launches IO parse and stores result; `MarkdownView` accepts `CharSequence` directly (no parsing in Main thread).
- Delta throttle: `ChatViewModel` accumulates deltas per-block in a `ConcurrentHashMap`, a 50ms ticker job flushes them to `_uiState`.
- FAB: `MessageList` takes a new `onScrollToBottom` callback and shows a FAB when `scrollFollowState == DETACHED` and not near bottom.

**Tech Stack:** Kotlin coroutines, Markwon 4.x, `InfiniteTransition`, `LazyListState`

---

## File Map

| File | Change |
|---|---|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt` | Add `renderedMarkdown: CharSequence?` to `TextBlock` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` | IO-thread Markdown parse on `TextBlockStop`; 50ms delta flush |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/MarkdownView.kt` | Accept `CharSequence` instead of `String` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt` | Pass `renderedMarkdown` to `MarkdownView`; animated cursor blink |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/MessageList.kt` | Add "回到底部" FAB |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` | Pass `onScrollToBottom` callback |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/AnimationTokens.kt` | Add `CURSOR_BLINK_DURATION_MS` |

---

### Task 1: Markdown IO-thread parsing

**Problem:** `MarkdownView.kt` comment claims IO pre-parsing, but `markwon.setMarkdown(textView, markdown)` runs in AndroidView's `update` callback on the **Main thread**. On large documents this causes jank. Fix: parse to `CharSequence` on IO in `ChatViewModel`, store in `TextBlock.renderedMarkdown`, pass to a simplified `MarkdownView` that only assigns it to `textView.text`.

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/MarkdownView.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt`

- [ ] **Step 1: Read `ContentBlock.kt`**

  Verify the current `TextBlock` definition before editing:

  ```bash
  grep -n "data class TextBlock" ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt
  ```

- [ ] **Step 2: Add `renderedMarkdown` field to `TextBlock`**

  In `ContentBlock.kt`, update `TextBlock`:

  ```kotlin
  data class TextBlock(
      override val blockId: String,
      val text: String,
      val done: Boolean = false,
      val renderedMarkdown: CharSequence? = null,
  ) : ContentBlock()
  ```

  `renderedMarkdown` is `null` while streaming (done=false) and gets populated after `TextBlockStop` triggers IO parse.

- [ ] **Step 3: Add Markwon to `ChatViewModel` and IO-parse on `TextBlockStop`**

  `ChatViewModel` needs a `Markwon` instance. Inject it via the constructor by creating a `MarkdownModule` Hilt module, or — simpler — inject `Application` context and build Markwon inside ViewModel. Since ViewModel already gets Android context via Hilt's `@ApplicationContext`, use that approach.

  Add import to `ChatViewModel.kt`:
  ```kotlin
  import android.content.Context
  import dagger.hilt.android.qualifiers.ApplicationContext
  import io.noties.markwon.Markwon
  import io.noties.markwon.ext.strikethrough.StrikethroughPlugin
  import io.noties.markwon.ext.tables.TablePlugin
  import kotlinx.coroutines.withContext
  ```

  Add `@ApplicationContext context: Context` to constructor:
  ```kotlin
  @HiltViewModel
  class ChatViewModel @Inject constructor(
      private val chatRepository: ChatRepository,
      private val settingsRepository: SettingsRepository,
      private val networkMonitor: NetworkMonitor,
      @ApplicationContext private val context: Context,
      @IoDispatcher private val dispatcher: CoroutineDispatcher,
  ) : ViewModel() {
  ```

  Add Markwon instance after the `_uiState` declaration:
  ```kotlin
  private val markwon: Markwon = Markwon.builder(context)
      .usePlugin(StrikethroughPlugin.create())
      .usePlugin(TablePlugin.create(context))
      .build()
  ```

  Update `handleEvent(TextBlockStop)` to parse on IO:
  ```kotlin
  is StreamEvent.TextBlockStop -> {
      viewModelScope.launch(dispatcher) {
          val msgId = currentAssistantMessageId ?: return@launch
          val rawText = _uiState.value.messages
              .find { it.id == msgId }
              ?.blocks?.find { it.blockId == event.blockId }
              ?.let { (it as? ContentBlock.TextBlock)?.text } ?: ""
          val rendered = withContext(Dispatchers.IO) {
              markwon.toMarkdown(rawText)
          }
          updateBlockInCurrentMessage(event.blockId) { existing ->
              if (existing is ContentBlock.TextBlock)
                  existing.copy(done = true, renderedMarkdown = rendered)
              else existing
          }
      }
  }
  ```

  > Note: `markwon.toMarkdown(text)` returns a `Spanned` which is a `CharSequence`.

- [ ] **Step 4: Update `MarkdownView` to accept `CharSequence`**

  Replace `MarkdownView.kt`:

  ```kotlin
  package com.sebastian.android.ui.common

  import android.widget.TextView
  import androidx.compose.material3.MaterialTheme
  import androidx.compose.runtime.Composable
  import androidx.compose.ui.Modifier
  import androidx.compose.ui.graphics.toArgb
  import androidx.compose.ui.viewinterop.AndroidView

  /**
   * Renders pre-parsed Markdown (Spanned CharSequence).
   * Parsing is done on IO thread in ChatViewModel; this composable only assigns
   * the result to TextView.text on the Main thread — zero parse work here.
   */
  @Composable
  fun MarkdownView(
      markdown: CharSequence,
      modifier: Modifier = Modifier,
  ) {
      val textColor = MaterialTheme.colorScheme.onSurface.toArgb()

      AndroidView(
          factory = { ctx ->
              TextView(ctx).apply {
                  setTextColor(textColor)
                  textSize = 16f
                  setLineSpacing(0f, 1.4f)
              }
          },
          update = { textView ->
              textView.setTextColor(textColor)
              textView.text = markdown
          },
          modifier = modifier,
      )
  }
  ```

- [ ] **Step 5: Update `StreamingMessage.kt` to pass `renderedMarkdown`**

  In `AssistantMessageBlocks`, update the `TextBlock` branch:

  ```kotlin
  is ContentBlock.TextBlock -> {
      if (block.done && block.renderedMarkdown != null) {
          MarkdownView(
              markdown = block.renderedMarkdown,
              modifier = Modifier.fillMaxWidth().alpha(alpha),
          )
      } else if (!block.done) {
          // Streaming in progress — plain text with animated cursor (added in Task 4)
          Text(
              text = block.text,
              style = MaterialTheme.typography.bodyLarge,
              color = MaterialTheme.colorScheme.onSurface,
              modifier = Modifier.fillMaxWidth().alpha(alpha),
          )
      } else {
          // done=true but renderedMarkdown=null (parse pending) — show plain text
          Text(
              text = block.text,
              style = MaterialTheme.typography.bodyLarge,
              color = MaterialTheme.colorScheme.onSurface,
              modifier = Modifier.fillMaxWidth().alpha(alpha),
          )
      }
  }
  ```

- [ ] **Step 6: Update `ChatViewModelTest` — mock context for Markwon**

  The `ChatViewModel` now requires `@ApplicationContext Context`. In the unit test, provide a mock:

  Add import:
  ```kotlin
  import android.content.Context
  ```

  Add field:
  ```kotlin
  private lateinit var mockContext: Context
  ```

  In `setup()`, before `viewModel = ChatViewModel(...)`:
  ```kotlin
  mockContext = mock()
  // Markwon needs a real context for plugin init; use ApplicationProvider in unit tests
  // with Robolectric, or simply use ApplicationProvider.getApplicationContext()
  // For now, skip Markwon parse in unit tests by providing real context via Robolectric.
  ```

  > **Note:** If the project does not use Robolectric, inject `Markwon` as a constructor parameter instead of building it inside the ViewModel. Create a `MarkdownParser` interface with a `parse(text: String): CharSequence` method, bind it in a Hilt module, and mock it in tests. This is cleaner but requires one extra file. The implementer should check if Robolectric is already in `build.gradle` (`testImplementation "org.robolectric:robolectric:..."`) before choosing an approach.

- [ ] **Step 7: Build and test**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest 2>&1 | tail -20
  ```

  Expected: all tests pass.

- [ ] **Step 8: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt \
          app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
          app/src/main/java/com/sebastian/android/ui/common/MarkdownView.kt \
          app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt \
          app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
  git commit -m "perf(android): Markdown 解析移至 IO 线程，MarkdownView 仅赋值不解析

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 2: 50ms delta debounce

**Problem:** Every `TextDelta` event immediately calls `_uiState.update { }`, triggering Compose recomposition. At typical LLM token rates (10–30 tokens/sec), this is acceptable, but at burst rates it creates unnecessary recomposition pressure. Fix: accumulate deltas in a `ConcurrentHashMap<blockId, StringBuilder>` and flush to state every 50ms via a ticker coroutine.

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`

- [ ] **Step 1: Add delta buffer and flush coroutine to `ChatViewModel`**

  Add import:
  ```kotlin
  import java.util.concurrent.ConcurrentHashMap
  import kotlinx.coroutines.delay
  ```

  Add field after `_uiState`:
  ```kotlin
  private val pendingDeltas = ConcurrentHashMap<String, StringBuilder>()
  ```

  Add flush coroutine to `init` block (after `observeNetwork()` and `bindAppLifecycle()`):
  ```kotlin
  init {
      observeNetwork()
      bindAppLifecycle()
      startDeltaFlusher()
  }

  private fun startDeltaFlusher() {
      viewModelScope.launch(dispatcher) {
          while (true) {
              delay(50L)
              if (pendingDeltas.isNotEmpty()) {
                  val snapshot = pendingDeltas.entries.toList()
                  pendingDeltas.clear()
                  val msgId = currentAssistantMessageId ?: continue
                  _uiState.update { state ->
                      state.copy(
                          messages = state.messages.map { msg ->
                              if (msg.id != msgId) return@map msg
                              msg.copy(
                                  blocks = msg.blocks.map { block ->
                                      val pending = snapshot.find { it.key == block.blockId }
                                          ?: return@map block
                                      if (block is ContentBlock.TextBlock)
                                          block.copy(text = block.text + pending.value.toString())
                                      else block
                                  },
                              )
                          },
                      )
                  }
              }
          }
      }
  }
  ```

  Update `handleEvent(TextDelta)` to accumulate instead of update immediately:

  Replace:
  ```kotlin
  is StreamEvent.TextDelta -> {
      updateBlockInCurrentMessage(event.blockId) { existing ->
          if (existing is ContentBlock.TextBlock) {
              existing.copy(text = existing.text + event.delta)
          } else existing
      }
  }
  ```

  With:
  ```kotlin
  is StreamEvent.TextDelta -> {
      pendingDeltas.getOrPut(event.blockId) { StringBuilder() }.append(event.delta)
  }
  ```

- [ ] **Step 2: Update `text_delta appends to TextBlock` test**

  The existing test `text_delta appends to TextBlock` advances the dispatcher and then waits for the text. With 50ms debounce, it needs `advanceTimeBy(50)` or `advanceUntilIdle()`. The test already uses `advanceUntilIdle()` which will advance the 50ms delay, so it should still pass.

  Run:
  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest" 2>&1 | tail -20
  ```

  Expected: all tests pass.

- [ ] **Step 3: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt
  git commit -m "perf(android): TextDelta 50ms 批量 flush，降低 Compose 重组频率

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 3: "回到底部" FAB

**Problem:** When `scrollFollowState == DETACHED` and the user is far from the bottom, the spec requires a floating action button to return to the bottom. `MessageList.kt` tracks scroll state but shows no FAB.

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/MessageList.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`

- [ ] **Step 1: Add `onScrollToBottom` callback and FAB to `MessageList`**

  Update `MessageList` signature to accept `onScrollToBottom`:

  ```kotlin
  @Composable
  fun MessageList(
      messages: List<Message>,
      scrollFollowState: ScrollFollowState,
      onUserScrolled: () -> Unit,
      onScrolledNearBottom: () -> Unit,
      onScrolledToBottom: () -> Unit,
      onScrollToBottom: () -> Unit,
      onToggleThinking: (String) -> Unit,
      onToggleTool: (String) -> Unit,
      modifier: Modifier = Modifier,
  ) {
  ```

  Wrap the `LazyColumn` in a `Box` and add the FAB:

  ```kotlin
  val showScrollToBottomFab by remember {
      derivedStateOf {
          scrollFollowState == ScrollFollowState.DETACHED && !isNearBottom
      }
  }

  LaunchedEffect(showScrollToBottomFab) {
      if (!showScrollToBottomFab && scrollFollowState == ScrollFollowState.DETACHED && isNearBottom) {
          onScrolledToBottom()
      }
  }

  Box(modifier = modifier) {
      LazyColumn(
          state = listState,
          modifier = Modifier.fillMaxSize(),
      ) {
          item { Spacer(Modifier.height(16.dp)) }
          items(messages, key = { it.id }) { message ->
              MessageBubble(
                  message = message,
                  onToggleThinking = onToggleThinking,
                  onToggleTool = onToggleTool,
                  modifier = Modifier.padding(vertical = 4.dp),
              )
          }
          item { Spacer(Modifier.height(8.dp)) }
      }

      AnimatedVisibility(
          visible = showScrollToBottomFab,
          modifier = Modifier
              .align(Alignment.BottomEnd)
              .padding(16.dp),
      ) {
          SmallFloatingActionButton(onClick = onScrollToBottom) {
              Icon(Icons.Default.KeyboardArrowDown, contentDescription = "回到底部")
          }
      }
  }
  ```

  Add required imports to `MessageList.kt`:
  ```kotlin
  import androidx.compose.animation.AnimatedVisibility
  import androidx.compose.foundation.layout.Box
  import androidx.compose.material.icons.Icons
  import androidx.compose.material.icons.filled.KeyboardArrowDown
  import androidx.compose.material3.SmallFloatingActionButton
  import androidx.compose.material3.Icon
  import androidx.compose.ui.Alignment
  import androidx.compose.ui.graphics.vector.ImageVector
  ```

- [ ] **Step 2: Wire `onScrollToBottom` in `ChatScreen.kt`**

  In `ChatScreen`, update `MessageList` call to add:
  ```kotlin
  onScrollToBottom = {
      chatViewModel.onScrolledToBottom()
  },
  ```

  Also add the scroll-to-bottom trigger in `MessageList` — when `onScrollToBottom` is called from the FAB, we need to actually scroll. Add a `LaunchedEffect` in `MessageList` for this:

  ```kotlin
  // Scroll to bottom on FAB click (imperative, animated)
  // This is done by exposing a scroll trigger via the onScrollToBottom lambda being
  // called from FAB onClick AND also actually scrolling the list.
  // Simple approach: track a triggerScroll flag
  ```

  Actually, the cleanest way: add an `onScrollToBottom: () -> Unit` and when the FAB is clicked, both call the callback (to update ViewModel state) AND scroll imperatively:

  ```kotlin
  SmallFloatingActionButton(
      onClick = {
          scope.launch { listState.animateScrollToItem(messages.size - 1) }
          onScrollToBottom()
      }
  ) {
      Icon(Icons.Default.KeyboardArrowDown, contentDescription = "回到底部")
  }
  ```

  For this, `MessageList` needs a `val scope = rememberCoroutineScope()`.

- [ ] **Step 3: Build and test**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest 2>&1 | tail -10
  ```

  Expected: `BUILD SUCCESSFUL`, all tests pass.

- [ ] **Step 4: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/ui/chat/MessageList.kt \
          app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
  git commit -m "feat(android): MessageList 添加「回到底部」FAB

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

