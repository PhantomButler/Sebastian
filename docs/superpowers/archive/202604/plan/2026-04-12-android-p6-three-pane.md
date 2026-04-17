# Android P6 Three-Pane Layout & Session Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `ChatScreen` from `ListDetailPaneScaffold` (two-pane) to `ThreePaneScaffold` (three-pane) so the right-side `TodoPanel` exists. Implement session switching: tapping a session in `SessionPanel` switches the active session, restarts SSE for that session, and loads its message history.

**Architecture:** `ChatScreen` uses `ThreePaneScaffold` with `listPane`=SessionPanel, `detailPane`=ChatContent, `extraPane`=TodoPanel. `ChatViewModel` gains `switchSession(sessionId)` which cancels the current SSE job, loads history via `getMessages`, and starts a new SSE subscription. `activeSessionId` is tracked in `ChatUiState` so `SessionPanel` can highlight the active entry.

**Tech Stack:** `androidx.compose.material3.adaptive` (ThreePaneScaffold), Kotlin coroutines, Hilt

**Prerequisites:** P5 plan complete (SseClient resilient, cancelTurn wired). P5-B optional but recommended.

---

## File Map

| File | Change |
|---|---|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` | Replace `ListDetailPaneScaffold` with `ThreePaneScaffold`; add right pane toggle; wire `onSessionClick` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` | Add `activeSessionId` to `ChatUiState`; add `switchSession(sessionId)` |
| `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt` | Test `switchSession` |

---

### Task 1: Add `activeSessionId` and `switchSession` to `ChatViewModel`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`

- [ ] **Step 1: Write the failing test**

  In `ChatViewModelTest.kt`, add:

  ```kotlin
  @Test
  fun `switchSession clears messages and sets activeSessionId`() = runTest(dispatcher) {
      viewModel.uiState.test {
          awaitItem() // initial

          // Pre-populate a message
          sseFlow.emit(StreamEvent.TurnReceived("s1"))
          sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
          dispatcher.scheduler.advanceUntilIdle()
          awaitItem() // streaming state

          viewModel.switchSession("session-42")
          dispatcher.scheduler.advanceUntilIdle()

          var found = false
          while (!found) {
              val state = awaitItem()
              if (state.activeSessionId == "session-42") {
                  found = true
                  assertTrue(state.messages.isEmpty())
              }
          }
          assertTrue(found)
      }
  }
  ```

  Run:
  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest.switchSession clears messages and sets activeSessionId" 2>&1 | tail -10
  ```

  Expected: FAIL (method doesn't exist yet).

- [ ] **Step 2: Add `activeSessionId` to `ChatUiState`**

  In `ChatViewModel.kt`, update `ChatUiState`:

  ```kotlin
  data class ChatUiState(
      val messages: List<Message> = emptyList(),
      val composerState: ComposerState = ComposerState.IDLE_EMPTY,
      val scrollFollowState: ScrollFollowState = ScrollFollowState.FOLLOWING,
      val agentAnimState: AgentAnimState = AgentAnimState.IDLE,
      val activeThinkingEffort: ThinkingEffort = ThinkingEffort.AUTO,
      val activeSessionId: String = "main",
      val isOffline: Boolean = false,
      val pendingApprovals: List<PendingApproval> = emptyList(),
      val error: String? = null,
  )
  ```

- [ ] **Step 3: Add `switchSession` function and update `startSseCollection` to use `activeSessionId`**

  Add `switchSession` in the public mutation surface section:

  ```kotlin
  fun switchSession(sessionId: String) {
      sseJob?.cancel()
      sseJob = null
      currentAssistantMessageId = null
      pendingTurnSessionId = null
      _uiState.update {
          it.copy(
              activeSessionId = sessionId,
              messages = emptyList(),
              composerState = ComposerState.IDLE_EMPTY,
              agentAnimState = AgentAnimState.IDLE,
              pendingApprovals = emptyList(),
          )
      }
      viewModelScope.launch(dispatcher) {
          // Load history for the new session
          chatRepository.getMessages(sessionId)
              .onSuccess { history ->
                  _uiState.update { it.copy(messages = history) }
              }
              .onFailure { e ->
                  _uiState.update { it.copy(error = e.message) }
              }
          // Start SSE for the new session
          startSseCollection()
      }
  }
  ```

  Update `startSseCollection` to read `activeSessionId` from state instead of hardcoding `"main"`:

  ```kotlin
  private fun startSseCollection() {
      sseJob = viewModelScope.launch(dispatcher) {
          val baseUrl = settingsRepository.serverUrl.first()
          val sessionId = _uiState.value.activeSessionId
          try {
              chatRepository.sessionStream(baseUrl, sessionId, "").collect { event ->
                  handleEvent(event)
              }
          } catch (e: Exception) {
              _uiState.update { it.copy(isOffline = true) }
          }
      }
  }
  ```

  Also update `cancelTurn` to use `activeSessionId`:

  ```kotlin
  fun cancelTurn() {
      _uiState.update { it.copy(composerState = ComposerState.CANCELLING) }
      viewModelScope.launch(dispatcher) {
          chatRepository.cancelTurn(_uiState.value.activeSessionId)
              .onFailure { e ->
                  _uiState.update { it.copy(composerState = ComposerState.IDLE_EMPTY, error = e.message) }
              }
      }
  }
  ```

- [ ] **Step 4: Run the new test**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest" 2>&1 | tail -20
  ```

  Expected: all tests pass including the new `switchSession` test.

- [ ] **Step 5: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
          app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
  git commit -m "feat(android): ChatViewModel 添加 switchSession 和 activeSessionId 状态

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 2: Migrate `ChatScreen` to `ThreePaneScaffold`

**Background:** `ThreePaneScaffold` is the underlying primitive in `androidx.compose.material3.adaptive.layout`. The current `ListDetailPaneScaffold` only has two panes. The three-pane version adds an `extraPane` for `TodoPanel` on the right.

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`

- [ ] **Step 1: Replace scaffold and add right-pane toggle**

  Replace the entire `ChatScreen` composable with:

  ```kotlin
  @OptIn(ExperimentalMaterial3AdaptiveApi::class, ExperimentalMaterial3Api::class)
  @Composable
  fun ChatScreen(
      navController: NavController,
      chatViewModel: ChatViewModel = hiltViewModel(),
      sessionViewModel: SessionViewModel = hiltViewModel(),
      settingsViewModel: SettingsViewModel = hiltViewModel(),
  ) {
      val chatState by chatViewModel.uiState.collectAsState()
      val sessionState by sessionViewModel.uiState.collectAsState()
      val scaffoldState = rememberThreePaneScaffoldState()
      val scope = rememberCoroutineScope()

      // Approval dialog (blocks other interaction when present)
      chatState.pendingApprovals.firstOrNull()?.let { approval ->
          ApprovalDialog(
              approval = approval,
              onGrant = { chatViewModel.grantApproval(it) },
              onDeny = { chatViewModel.denyApproval(it) },
          )
      }

      ThreePaneScaffold(
          scaffoldState = scaffoldState,
          listPane = {
              AnimatedPane {
                  SessionPanel(
                      sessions = sessionState.sessions,
                      activeSessionId = chatState.activeSessionId,
                      onSessionClick = { session ->
                          chatViewModel.switchSession(session.id)
                          scope.launch {
                              scaffoldState.navigateTo(ThreePaneScaffoldRole.Detail)
                          }
                      },
                      onNewSession = sessionViewModel::createSession,
                      onNavigateToSettings = {
                          navController.navigate(Route.Settings) { launchSingleTop = true }
                      },
                      onNavigateToSubAgents = {
                          navController.navigate(Route.SubAgents) { launchSingleTop = true }
                      },
                  )
              }
          },
          detailPane = {
              AnimatedPane {
                  Scaffold(
                      topBar = {
                          TopAppBar(
                              title = { Text("Sebastian") },
                              navigationIcon = {
                                  IconButton(onClick = {
                                      scope.launch {
                                          scaffoldState.navigateTo(ThreePaneScaffoldRole.List)
                                      }
                                  }) {
                                      Icon(Icons.Default.Menu, contentDescription = "会话列表")
                                  }
                              },
                              actions = {
                                  IconButton(onClick = {
                                      scope.launch {
                                          scaffoldState.navigateTo(ThreePaneScaffoldRole.Extra)
                                      }
                                  }) {
                                      Icon(
                                          Icons.Default.List,
                                          contentDescription = "任务进度",
                                      )
                                  }
                              },
                          )
                      },
                  ) { innerPadding ->
                      Column(
                          modifier = Modifier
                              .fillMaxSize()
                              .padding(innerPadding)
                              .imePadding(),
                      ) {
                          MessageList(
                              messages = chatState.messages,
                              scrollFollowState = chatState.scrollFollowState,
                              onUserScrolled = chatViewModel::onUserScrolled,
                              onScrolledNearBottom = chatViewModel::onScrolledNearBottom,
                              onScrolledToBottom = chatViewModel::onScrolledToBottom,
                              onToggleThinking = chatViewModel::toggleThinkingBlock,
                              onToggleTool = chatViewModel::toggleToolBlock,
                              modifier = Modifier.weight(1f),
                          )
                          val providers by settingsViewModel.uiState.collectAsState()
                          Composer(
                              state = chatState.composerState,
                              activeProvider = providers.providers.firstOrNull { it.isDefault },
                              effort = chatState.activeThinkingEffort,
                              onEffortChange = chatViewModel::setEffort,
                              onSend = chatViewModel::sendMessage,
                              onStop = chatViewModel::cancelTurn,
                          )
                      }
                  }
              }
          },
          extraPane = {
              AnimatedPane {
                  TodoPanel()
              }
          },
      )
  }
  ```

  Update imports — remove `ListDetailPaneScaffold`/`ListDetailPaneScaffoldRole`/`rememberListDetailPaneScaffoldNavigator`, add:
  ```kotlin
  import androidx.compose.material.icons.filled.List
  import androidx.compose.material3.adaptive.layout.ThreePaneScaffold
  import androidx.compose.material3.adaptive.layout.ThreePaneScaffoldRole
  import androidx.compose.material3.adaptive.navigation.rememberThreePaneScaffoldState
  ```

- [ ] **Step 2: Verify build**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:compileDebugKotlin 2>&1 | tail -20
  ```

  If `ThreePaneScaffold` or `rememberThreePaneScaffoldState` is not found, check the exact class names available in the adaptive library:

  ```bash
  ./gradlew :app:dependencies --configuration debugCompileClasspath 2>&1 | grep "adaptive"
  ```

  The adaptive library may expose the three-pane scaffold via `SupportingPaneScaffold` or via `ThreePaneScaffold` in `layout` package. Adjust imports accordingly if needed.

  Expected: `BUILD SUCCESSFUL`

- [ ] **Step 3: Run all tests**

  ```bash
  ./gradlew :app:testDebugUnitTest 2>&1 | tail -10
  ```

  Expected: all pass.

- [ ] **Step 4: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
  git commit -m "feat(android): ChatScreen 迁移到 ThreePaneScaffold，接入 TodoPanel 右侧面板

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 3: Session switching end-to-end

This task verifies session clicking actually works — `SessionViewModel` creates sessions, `ChatViewModel` switches to them.

**Files:**
- No new files; verifies integration of Tasks 1–2.

- [ ] **Step 1: Verify `SessionViewModel` passes sessions correctly**

  Check `SessionViewModel.uiState.sessions` is populated (should already work from P3). If `sessions` is empty after `loadSessions()`, the issue is in `SessionViewModel` — not in scope here.

- [ ] **Step 2: Verify `SessionPanel` `activeSessionId` highlighting**

  `SessionPanel.kt` already accepts `activeSessionId` and highlights the matching session with `surfaceVariant` background (implemented in P3). No changes needed.

- [ ] **Step 3: Verify `sendMessage` uses `activeSessionId`**

  In `ChatViewModel.sendMessage()`, the `userMsg` is created with `sessionId = "main"`. Update it to use `activeSessionId`:

  ```kotlin
  fun sendMessage(text: String) {
      if (text.isBlank()) return
      val userMsg = Message(
          id = UUID.randomUUID().toString(),
          sessionId = _uiState.value.activeSessionId,
          role = MessageRole.USER,
          text = text,
      )
      _uiState.update { state ->
          state.copy(
              messages = state.messages + userMsg,
              composerState = ComposerState.SENDING,
              scrollFollowState = ScrollFollowState.FOLLOWING,
          )
      }
      viewModelScope.launch(dispatcher) {
          chatRepository.sendTurn(text, _uiState.value.activeThinkingEffort)
              .onFailure { e ->
                  _uiState.update { it.copy(composerState = ComposerState.IDLE_READY, error = e.message) }
              }
      }
  }
  ```

- [ ] **Step 4: Run all tests**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest 2>&1 | tail -10
  ```

  Expected: all pass.

- [ ] **Step 5: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt
  git commit -m "fix(android): sendMessage 使用 activeSessionId 替换硬编码 main

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```
