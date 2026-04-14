# Android P5 Network Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 correctness and resilience issues found in spec/quality review of the Android native client: eliminate `runBlocking` in OkHttp interceptor, wire `cancelTurn` to the backend API, add SSE reconnection with exponential backoff, fix silent error drops in approval callbacks, fix `ChatViewModelTest` dispatcher setup, and add `launchSingleTop` to all navigation calls.

**Architecture:** Each task is independent (no cross-task deps). Tasks 1–3 form a network/cancellation cohesion group; Task 4 is a standalone SseClient refactor; Task 5 is a one-line ViewModel patch; Task 6 is test infrastructure; Task 7 is UI nav guard.

**Tech Stack:** Kotlin 2.x, Jetpack Compose, Hilt 2.52, OkHttp 4 SSE, Retrofit 2, Turbine, kotlinx.coroutines.test

---

## File Map

| File | Change |
|---|---|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/di/NetworkModule.kt` | Replace `runBlocking` with `AtomicReference` + background coroutine |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt` | Add `cancelSession` endpoint |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt` | Add `cancelTurn` to interface |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt` | Implement `cancelTurn` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` | Wire `cancelTurn` + fix approval error handling |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/SseClient.kt` | Add `sseFlowOnce` + `resilientSseFlow` with backoff |
| `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt` | Add `Dispatchers.setMain/resetMain` + cancelTurn test |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt` | `launchSingleTop = true` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderListPage.kt` | `launchSingleTop = true` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` | `launchSingleTop = true` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/AgentListScreen.kt` | `launchSingleTop = true` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/SessionListScreen.kt` | `launchSingleTop = true` |

---

### Task 1: Fix `runBlocking` in `NetworkModule`

**Problem:** `baseUrlInterceptor` calls `runBlocking { settingsDataStore.serverUrl.first() }` on every HTTP request, blocking an OkHttp thread-pool thread and risking deadlock.

**Fix:** Cache the URL in an `AtomicReference<String>` updated by a background `CoroutineScope` that collects `serverUrl`. The interceptor reads the cached value without blocking.

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/di/NetworkModule.kt`

- [ ] **Step 1: Write the failing test**

  There is no direct unit test for the interceptor — the regression test is `ChatViewModelTest.sendMessage adds user message` which would deadlock if runBlocking ever blocked. Confirm the existing test suite compiles and passes before making changes:

  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest" 2>&1 | tail -20
  ```

  Expected: all ChatViewModelTest tests pass (even if flaky without setMain — that gets fixed in Task 6).

- [ ] **Step 2: Replace `runBlocking` with `AtomicReference` cache**

  Replace the entire `provideOkHttpClient` function in `NetworkModule.kt`:

  **Remove these imports:**
  ```kotlin
  import kotlinx.coroutines.flow.first
  import kotlinx.coroutines.runBlocking
  ```

  **Add these imports:**
  ```kotlin
  import java.util.concurrent.atomic.AtomicReference
  import kotlinx.coroutines.CoroutineScope
  import kotlinx.coroutines.Dispatchers
  import kotlinx.coroutines.SupervisorJob
  import kotlinx.coroutines.launch
  ```

  **Replace the function body:**
  ```kotlin
  @Provides @Singleton
  fun provideOkHttpClient(
      tokenStore: SecureTokenStore,
      settingsDataStore: SettingsDataStore,
  ): OkHttpClient {
      val authInterceptor = Interceptor { chain ->
          val token = tokenStore.getToken()
          val req = if (token != null) {
              chain.request().newBuilder()
                  .header("Authorization", "Bearer $token")
                  .build()
          } else chain.request()
          chain.proceed(req)
      }

      // Cache server URL to avoid runBlocking on OkHttp threads.
      // Background coroutine keeps the cache fresh whenever DataStore emits.
      val cachedUrl = AtomicReference<String>("")
      CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
          settingsDataStore.serverUrl.collect { url -> cachedUrl.set(url) }
      }

      val baseUrlInterceptor = Interceptor { chain ->
          val serverUrl = cachedUrl.get().trimEnd('/')
          val original = chain.request()
          if (serverUrl.isEmpty()) return@Interceptor chain.proceed(original)
          val base = "$serverUrl/".toHttpUrlOrNull()
              ?: return@Interceptor chain.proceed(original)
          val newUrl = original.url.newBuilder()
              .scheme(base.scheme)
              .host(base.host)
              .port(base.port)
              .build()
          chain.proceed(original.newBuilder().url(newUrl).build())
      }

      val logging = HttpLoggingInterceptor().apply {
          level = if (BuildConfig.DEBUG) HttpLoggingInterceptor.Level.BASIC
                  else HttpLoggingInterceptor.Level.NONE
      }

      return OkHttpClient.Builder()
          .addInterceptor(baseUrlInterceptor)
          .addInterceptor(authInterceptor)
          .addInterceptor(logging)
          .build()
  }
  ```

- [ ] **Step 3: Verify build passes**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:compileDebugKotlin 2>&1 | tail -20
  ```

  Expected: `BUILD SUCCESSFUL`

- [ ] **Step 4: Commit**

  ```bash
  cd ui/mobile-android
  git add app/src/main/java/com/sebastian/android/di/NetworkModule.kt
  git commit -m "fix(android): 用 AtomicReference 替换 NetworkModule 中的 runBlocking

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 2: Add `cancelSession` API endpoint and `cancelTurn` repository method

**Problem:** `ChatViewModel.cancelTurn()` only changes local `ComposerState` and never calls the backend cancel API. The API endpoint and repository method need to be added first before wiring the ViewModel.

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt`

- [ ] **Step 1: Add `cancelSession` to `ApiService.kt`**

  Add after the `deleteSession` method (line 30):

  ```kotlin
  @POST("api/v1/sessions/{sessionId}/cancel")
  suspend fun cancelSession(@Path("sessionId") sessionId: String): OkResponse
  ```

- [ ] **Step 2: Add `cancelTurn` to `ChatRepository` interface**

  Add to `ChatRepository.kt`:

  ```kotlin
  suspend fun cancelTurn(sessionId: String): Result<Unit>
  ```

  Full updated interface:
  ```kotlin
  interface ChatRepository {
      fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String? = null): Flow<StreamEvent>
      fun globalStream(baseUrl: String, lastEventId: String? = null): Flow<StreamEvent>
      suspend fun getMessages(sessionId: String): Result<List<Message>>
      suspend fun sendTurn(content: String, effort: ThinkingEffort): Result<Unit>
      suspend fun sendSessionTurn(sessionId: String, content: String, effort: ThinkingEffort): Result<Unit>
      suspend fun cancelTurn(sessionId: String): Result<Unit>
      suspend fun grantApproval(approvalId: String): Result<Unit>
      suspend fun denyApproval(approvalId: String): Result<Unit>
  }
  ```

- [ ] **Step 3: Implement `cancelTurn` in `ChatRepositoryImpl.kt`**

  Add after `sendSessionTurn`:

  ```kotlin
  override suspend fun cancelTurn(sessionId: String): Result<Unit> = runCatching {
      apiService.cancelSession(sessionId)
      Unit
  }
  ```

- [ ] **Step 4: Verify build**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:compileDebugKotlin 2>&1 | tail -20
  ```

  Expected: `BUILD SUCCESSFUL`

- [ ] **Step 5: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/data/remote/ApiService.kt \
          app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt \
          app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt
  git commit -m "feat(android): 添加 cancelSession API 端点和 ChatRepository.cancelTurn 方法

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 3: Wire `ChatViewModel.cancelTurn()` to call repository

**Problem:** `cancelTurn()` only sets `ComposerState.CANCELLING` locally. It must also call `chatRepository.cancelTurn(sessionId)` and handle errors.

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`

- [ ] **Step 1: Update `cancelTurn()` in `ChatViewModel.kt`**

  Replace:
  ```kotlin
  fun cancelTurn() {
      _uiState.update { it.copy(composerState = ComposerState.CANCELLING) }
  }
  ```

  With:
  ```kotlin
  fun cancelTurn() {
      _uiState.update { it.copy(composerState = ComposerState.CANCELLING) }
      viewModelScope.launch(dispatcher) {
          chatRepository.cancelTurn("main")
              .onFailure { e ->
                  _uiState.update { it.copy(composerState = ComposerState.IDLE_EMPTY, error = e.message) }
              }
      }
  }
  ```

- [ ] **Step 2: Fix `grantApproval` and `denyApproval` to surface errors** (minor patch while in this file)

  Replace:
  ```kotlin
  fun grantApproval(approvalId: String) {
      viewModelScope.launch(dispatcher) {
          chatRepository.grantApproval(approvalId)
      }
  }

  fun denyApproval(approvalId: String) {
      viewModelScope.launch(dispatcher) {
          chatRepository.denyApproval(approvalId)
      }
  }
  ```

  With:
  ```kotlin
  fun grantApproval(approvalId: String) {
      viewModelScope.launch(dispatcher) {
          chatRepository.grantApproval(approvalId)
              .onFailure { e -> _uiState.update { it.copy(error = e.message) } }
      }
  }

  fun denyApproval(approvalId: String) {
      viewModelScope.launch(dispatcher) {
          chatRepository.denyApproval(approvalId)
              .onFailure { e -> _uiState.update { it.copy(error = e.message) } }
      }
  }
  ```

- [ ] **Step 3: Verify build**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:compileDebugKotlin 2>&1 | tail -20
  ```

  Expected: `BUILD SUCCESSFUL`

- [ ] **Step 4: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt
  git commit -m "fix(android): cancelTurn 调用后端 API，approval 回调补充错误处理

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 4: SSE reconnection with exponential backoff

**Problem:** `SseClient.sseFlow` calls `close(exception)` in `onFailure`, which terminates the flow immediately. Any network blip kills the stream forever. There is also no Last-Event-ID tracking across reconnects.

**Fix:** Extract `sseFlowOnce` (single-attempt, emits `Pair<String?, StreamEvent>`), then wrap in `resilientSseFlow` that retries with delays `[1s, 2s, 4s]` (max 3 attempts) and threads `lastEventId` across reconnects. Clean server close (`onClosed`) still stops collection without retry.

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/SseClient.kt`

- [ ] **Step 1: Replace `SseClient.kt` with resilient implementation**

  Full file content:

  ```kotlin
  package com.sebastian.android.data.remote

  import com.sebastian.android.data.model.StreamEvent
  import com.sebastian.android.data.remote.dto.SseFrameParser
  import kotlinx.coroutines.Dispatchers
  import kotlinx.coroutines.channels.awaitClose
  import kotlinx.coroutines.delay
  import kotlinx.coroutines.flow.Flow
  import kotlinx.coroutines.flow.callbackFlow
  import kotlinx.coroutines.flow.flow
  import kotlinx.coroutines.flow.flowOn
  import okhttp3.OkHttpClient
  import okhttp3.Request
  import okhttp3.Response
  import okhttp3.sse.EventSource
  import okhttp3.sse.EventSourceListener
  import okhttp3.sse.EventSources
  import javax.inject.Inject
  import javax.inject.Singleton

  @Singleton
  class SseClient @Inject constructor(
      private val okHttpClient: OkHttpClient,
  ) {
      /**
       * Subscribes to a single-session event stream with automatic reconnection.
       */
      fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String? = null): Flow<StreamEvent> =
          resilientSseFlow("$baseUrl/api/v1/sessions/$sessionId/stream", lastEventId)

      /**
       * Subscribes to the global event stream with automatic reconnection.
       */
      fun globalStream(baseUrl: String, lastEventId: String? = null): Flow<StreamEvent> =
          resilientSseFlow("$baseUrl/api/v1/stream", lastEventId)

      /**
       * Single-attempt SSE connection. Emits (eventId, StreamEvent) pairs.
       * Closes normally on server-initiated close; closes with exception on network failure.
       */
      private fun sseFlowOnce(url: String, lastEventId: String?): Flow<Pair<String?, StreamEvent>> = callbackFlow {
          val requestBuilder = Request.Builder().url(url)
          lastEventId?.let { requestBuilder.header("Last-Event-Id", it) }
          val request = requestBuilder.build()

          val listener = object : EventSourceListener() {
              override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                  val event = SseFrameParser.parse(data)
                  trySend(Pair(id, event))
              }

              override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                  close(t ?: Exception("SSE connection failed: ${response?.code}"))
              }

              override fun onClosed(eventSource: EventSource) {
                  close()
              }
          }

          val eventSource = EventSources.createFactory(okHttpClient)
              .newEventSource(request, listener)

          awaitClose { eventSource.cancel() }
      }.flowOn(Dispatchers.IO)

      /**
       * Resilient SSE flow: reconnects on failure with exponential backoff (1s, 2s, 4s, max 3 retries).
       * Tracks Last-Event-ID across reconnects so the server can resume from the last delivered event.
       * A clean server close (onClosed) terminates the flow without retry.
       */
      private fun resilientSseFlow(url: String, initialLastEventId: String?): Flow<StreamEvent> = flow {
          var lastEventId = initialLastEventId
          var attempt = 0
          val delaysMs = longArrayOf(1_000L, 2_000L, 4_000L)

          while (true) {
              try {
                  sseFlowOnce(url, lastEventId).collect { (id, event) ->
                      if (id != null) lastEventId = id
                      emit(event)
                      attempt = 0 // reset backoff counter on successful event
                  }
                  // Flow completed cleanly — server closed connection, no retry
                  break
              } catch (e: Exception) {
                  if (attempt >= delaysMs.size) throw e
                  delay(delaysMs[attempt])
                  attempt++
              }
          }
      }.flowOn(Dispatchers.IO)
  }
  ```

- [ ] **Step 2: Verify build and existing SSE parser tests still pass**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.SseFrameParserTest" 2>&1 | tail -20
  ```

  Expected: `5 tests completed, 0 failed`

- [ ] **Step 3: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/data/remote/SseClient.kt
  git commit -m "feat(android): SseClient 增加断线重连与 Last-Event-ID 追踪

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 5: Fix `ChatViewModelTest` — dispatcher setup

**Problem:** `ChatViewModelTest` never calls `Dispatchers.setMain(dispatcher)`, so `viewModelScope.launch` on the main dispatcher runs on the real main thread (unavailable in unit tests), causing test flakiness or silent no-ops. There is also no `@After` to clean up. The `cancelTurn` method added in Task 3 has no test coverage.

**Files:**
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`

- [ ] **Step 1: Add imports and `@After` teardown**

  Add to the imports block:
  ```kotlin
  import kotlinx.coroutines.Dispatchers
  import kotlinx.coroutines.test.resetMain
  import kotlinx.coroutines.test.setMain
  import org.junit.After
  ```

  Add `Dispatchers.setMain(dispatcher)` as the **first line** of `setup()`:
  ```kotlin
  @Before
  fun setup() {
      Dispatchers.setMain(dispatcher)
      chatRepository = mock()
      settingsRepository = mock()
      whenever(settingsRepository.serverUrl).thenReturn(serverUrlFlow)
      whenever(chatRepository.sessionStream(any(), any(), any())).thenReturn(sseFlow)
      whenever(chatRepository.globalStream(any(), any())).thenReturn(flowOf())
      runBlocking {
          whenever(chatRepository.sendTurn(any(), any())).thenReturn(Result.success(Unit))
          whenever(chatRepository.cancelTurn(any())).thenReturn(Result.success(Unit))
          whenever(chatRepository.grantApproval(any())).thenReturn(Result.success(Unit))
          whenever(chatRepository.denyApproval(any())).thenReturn(Result.success(Unit))
      }
      viewModel = ChatViewModel(chatRepository, settingsRepository, dispatcher)
  }
  ```

  Add `@After` method after `setup()`:
  ```kotlin
  @After
  fun tearDown() {
      Dispatchers.resetMain()
  }
  ```

- [ ] **Step 2: Add `cancelTurn` test**

  Add this test at the end of the class (before the closing `}`):

  ```kotlin
  @Test
  fun `cancelTurn sets state CANCELLING and calls repository`() = runTest(dispatcher) {
      viewModel.uiState.test {
          awaitItem() // initial

          viewModel.cancelTurn()
          dispatcher.scheduler.advanceUntilIdle()

          val state = awaitItem()
          assertEquals(ComposerState.CANCELLING, state.composerState)
          runBlocking { verify(chatRepository).cancelTurn("main") }
      }
  }
  ```

- [ ] **Step 3: Run all ViewModel tests**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest" 2>&1 | tail -30
  ```

  Expected: `12 tests completed, 0 failed` (11 existing + 1 new cancelTurn test)

- [ ] **Step 4: Commit**

  ```bash
  git add app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
  git commit -m "test(android): ChatViewModelTest 补充 Dispatchers.setMain 和 cancelTurn 测试

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 6: Add `launchSingleTop = true` to all `navController.navigate()` calls

**Problem:** Double-tapping any navigation item pushes duplicate destinations onto the back stack. All `navController.navigate()` calls need `launchSingleTop = true` in their `NavOptionsBuilder`.

**Affected files:** 5 files, 8 call sites total.

- [ ] **Step 1: Fix `ChatScreen.kt` (2 calls)**

  File: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`

  Replace:
  ```kotlin
  onNavigateToSettings = { navController.navigate(Route.Settings) },
  onNavigateToSubAgents = { navController.navigate(Route.SubAgents) },
  ```

  With:
  ```kotlin
  onNavigateToSettings = { navController.navigate(Route.Settings) { launchSingleTop = true } },
  onNavigateToSubAgents = { navController.navigate(Route.SubAgents) { launchSingleTop = true } },
  ```

- [ ] **Step 2: Fix `SettingsScreen.kt` (2 calls)**

  File: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt`

  Replace:
  ```kotlin
  onClick = { navController.navigate(Route.SettingsConnection) },
  ```
  With:
  ```kotlin
  onClick = { navController.navigate(Route.SettingsConnection) { launchSingleTop = true } },
  ```

  Replace:
  ```kotlin
  onClick = { navController.navigate(Route.SettingsProviders) },
  ```
  With:
  ```kotlin
  onClick = { navController.navigate(Route.SettingsProviders) { launchSingleTop = true } },
  ```

- [ ] **Step 3: Fix `ProviderListPage.kt` (2 calls)**

  File: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/ProviderListPage.kt`

  Replace:
  ```kotlin
  FloatingActionButton(onClick = { navController.navigate(Route.SettingsProvidersNew) }) {
  ```
  With:
  ```kotlin
  FloatingActionButton(onClick = { navController.navigate(Route.SettingsProvidersNew) { launchSingleTop = true } }) {
  ```

  Replace:
  ```kotlin
  onEdit = { navController.navigate(Route.SettingsProvidersEdit(provider.id)) },
  ```
  With:
  ```kotlin
  onEdit = { navController.navigate(Route.SettingsProvidersEdit(provider.id)) { launchSingleTop = true } },
  ```

- [ ] **Step 4: Fix `AgentListScreen.kt` (1 call)**

  File: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/AgentListScreen.kt`

  Replace:
  ```kotlin
  navController.navigate(Route.AgentSessions(agent.agentType))
  ```
  With:
  ```kotlin
  navController.navigate(Route.AgentSessions(agent.agentType)) { launchSingleTop = true }
  ```

- [ ] **Step 5: Fix `SessionListScreen.kt` (1 call)**

  File: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/SessionListScreen.kt`

  Replace:
  ```kotlin
  navController.navigate(Route.SessionDetail(session.id))
  ```
  With:
  ```kotlin
  navController.navigate(Route.SessionDetail(session.id)) { launchSingleTop = true }
  ```

- [ ] **Step 6: Verify build and all tests**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest 2>&1 | tail -20
  ```

  Expected: `BUILD SUCCESSFUL`, all tests pass.

- [ ] **Step 7: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt \
          app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt \
          app/src/main/java/com/sebastian/android/ui/settings/ProviderListPage.kt \
          app/src/main/java/com/sebastian/android/ui/subagents/AgentListScreen.kt \
          app/src/main/java/com/sebastian/android/ui/subagents/SessionListScreen.kt
  git commit -m "fix(android): 所有 navigate 调用加 launchSingleTop 防重复入栈

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

## Self-Review

**Spec coverage:**
- ✅ `runBlocking` in interceptor → Task 1
- ✅ `cancelTurn` no-op → Tasks 2 + 3
- ✅ SSE no retry/reconnect → Task 4
- ✅ SSE Last-Event-ID ignored → Task 4 (`sseFlowOnce` emits `id`)
- ✅ `grantApproval`/`denyApproval` silent error drop → Task 3 (Step 2)
- ✅ `ChatViewModelTest` missing `setMain` → Task 5
- ✅ `launchSingleTop` missing → Task 6 (5 files, 8 call sites)

**Placeholder scan:** No TBDs or TODOs. All steps contain exact code.

**Type consistency:**
- `cancelTurn(sessionId: String): Result<Unit>` declared in Task 2, used in Task 3 (`cancelTurn("main")`), tested in Task 5 (`verify(chatRepository).cancelTurn("main")`)
- `sseFlowOnce` returns `Flow<Pair<String?, StreamEvent>>` and is collected by `resilientSseFlow` as `{ (id, event) -> ... }` — consistent throughout Task 4
- `OkResponse` return type of `cancelSession` matches existing `grantApproval`/`denyApproval` pattern in `ApiService`
