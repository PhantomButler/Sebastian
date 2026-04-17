# Android P5-B Connectivity & Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two correctness gaps missed from P5: (1) SSE exhausted retries must set `isOffline = true`; (2) app going to background should disconnect SSE, and returning to foreground should reconnect; (3) `ConnectivityManager` must observe network changes and trigger reconnect when connectivity is restored.

**Architecture:** New `NetworkMonitor` singleton wraps `ConnectivityManager` as a `Flow<Boolean>`. `ChatViewModel` is extended with a tracked SSE job, lifecycle observer via `ProcessLifecycleOwner`, and network observation. Hilt wires `NetworkMonitor` automatically.

**Tech Stack:** Kotlin coroutines, `ConnectivityManager.NetworkCallback`, `ProcessLifecycleOwner.DefaultLifecycleObserver`, Hilt `@Singleton`

**Prerequisites:** P5 plan complete (SseClient has `resilientSseFlow` with exponential backoff).

---

## File Map

| File | Change |
|---|---|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/local/NetworkMonitor.kt` | New — `Flow<Boolean>` connectivity wrapper |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` | Track SSE job, observe network, add lifecycle binding |
| `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt` | Mock `NetworkMonitor`, test offline state |

---

### Task 1: `NetworkMonitor` — `Flow<Boolean>` connectivity wrapper

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/local/NetworkMonitor.kt`

- [ ] **Step 1: Write the failing test**

  Create `ui/mobile-android/app/src/test/java/com/sebastian/android/data/local/NetworkMonitorTest.kt`:

  ```kotlin
  package com.sebastian.android.data.local

  import org.junit.Test
  import org.junit.Assert.assertNotNull

  class NetworkMonitorTest {
      @Test
      fun `NetworkMonitor can be instantiated`() {
          // Smoke test — real ConnectivityManager can't be exercised in unit tests.
          // Integration behaviour is verified via ChatViewModel tests with a mock.
          assertNotNull(NetworkMonitor::class)
      }
  }
  ```

  Run it:
  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.local.NetworkMonitorTest" 2>&1 | tail -10
  ```

  Expected: `BUILD SUCCESSFUL` (class doesn't exist yet, so compile error) — confirms test will fail first.

- [ ] **Step 2: Create `NetworkMonitor.kt`**

  ```kotlin
  package com.sebastian.android.data.local

  import android.content.Context
  import android.net.ConnectivityManager
  import android.net.Network
  import android.net.NetworkCapabilities
  import android.net.NetworkRequest
  import dagger.hilt.android.qualifiers.ApplicationContext
  import kotlinx.coroutines.Dispatchers
  import kotlinx.coroutines.channels.awaitClose
  import kotlinx.coroutines.flow.Flow
  import kotlinx.coroutines.flow.callbackFlow
  import kotlinx.coroutines.flow.distinctUntilChanged
  import kotlinx.coroutines.flow.flowOn
  import javax.inject.Inject
  import javax.inject.Singleton

  @Singleton
  class NetworkMonitor @Inject constructor(
      @ApplicationContext private val context: Context,
  ) {
      /** Emits `true` when internet is available, `false` when lost. Distinct-until-changed. */
      val isOnline: Flow<Boolean> = callbackFlow {
          val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

          val callback = object : ConnectivityManager.NetworkCallback() {
              override fun onAvailable(network: Network) { trySend(true) }
              override fun onLost(network: Network) { trySend(false) }
          }

          val request = NetworkRequest.Builder()
              .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
              .build()
          cm.registerNetworkCallback(request, callback)

          // Emit current state immediately
          val isConnected = cm.activeNetwork?.let {
              cm.getNetworkCapabilities(it)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
          } ?: false
          trySend(isConnected)

          awaitClose { cm.unregisterNetworkCallback(callback) }
      }.flowOn(Dispatchers.IO).distinctUntilChanged()
  }
  ```

- [ ] **Step 3: Verify test passes**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.local.NetworkMonitorTest" 2>&1 | tail -10
  ```

  Expected: `1 test completed, 0 failed`

- [ ] **Step 4: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/data/local/NetworkMonitor.kt \
          app/src/test/java/com/sebastian/android/data/local/NetworkMonitorTest.kt
  git commit -m "feat(android): 添加 NetworkMonitor 封装 ConnectivityManager 为 Flow<Boolean>

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 2: Wire `ChatViewModel` — offline detection, network-triggered reconnect, lifecycle awareness

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`

- [ ] **Step 1: Update `ChatViewModel` constructor to inject `NetworkMonitor`**

  Add import:
  ```kotlin
  import androidx.lifecycle.DefaultLifecycleObserver
  import androidx.lifecycle.LifecycleOwner
  import androidx.lifecycle.ProcessLifecycleOwner
  import com.sebastian.android.data.local.NetworkMonitor
  ```

  Update the constructor:
  ```kotlin
  @HiltViewModel
  class ChatViewModel @Inject constructor(
      private val chatRepository: ChatRepository,
      private val settingsRepository: SettingsRepository,
      private val networkMonitor: NetworkMonitor,
      @IoDispatcher private val dispatcher: CoroutineDispatcher,
  ) : ViewModel() {
  ```

- [ ] **Step 2: Replace `init` block and `startSseCollection` with lifecycle-aware + network-reactive version**

  Replace the current `init` block and `startSseCollection` function:

  ```kotlin
  private var sseJob: Job? = null

  init {
      observeNetwork()
      bindAppLifecycle()
  }

  private fun observeNetwork() {
      viewModelScope.launch(dispatcher) {
          networkMonitor.isOnline.collect { isOnline ->
              _uiState.update { it.copy(isOffline = !isOnline) }
              if (isOnline && sseJob?.isActive != true) {
                  startSseCollection()
              }
          }
      }
  }

  private fun bindAppLifecycle() {
      ProcessLifecycleOwner.get().lifecycle.addObserver(object : DefaultLifecycleObserver {
          override fun onStart(owner: LifecycleOwner) {
              if (sseJob?.isActive != true && !_uiState.value.isOffline) {
                  startSseCollection()
              }
          }

          override fun onStop(owner: LifecycleOwner) {
              sseJob?.cancel()
              sseJob = null
          }
      })
  }

  private fun startSseCollection() {
      sseJob = viewModelScope.launch(dispatcher) {
          val baseUrl = settingsRepository.serverUrl.first()
          try {
              chatRepository.sessionStream(baseUrl, "main", "").collect { event ->
                  handleEvent(event)
              }
          } catch (e: Exception) {
              _uiState.update { it.copy(isOffline = true) }
          }
      }
  }
  ```

- [ ] **Step 3: Update `ChatViewModelTest` to mock `NetworkMonitor`**

  Add import at top of test file:
  ```kotlin
  import com.sebastian.android.data.local.NetworkMonitor
  ```

  Add field:
  ```kotlin
  private lateinit var networkMonitor: NetworkMonitor
  private val onlineFlow = MutableStateFlow(true)
  ```

  Add in `setup()`, before `viewModel = ChatViewModel(...)`:
  ```kotlin
  networkMonitor = mock()
  whenever(networkMonitor.isOnline).thenReturn(onlineFlow)
  ```

  Update ViewModel construction:
  ```kotlin
  viewModel = ChatViewModel(chatRepository, settingsRepository, networkMonitor, dispatcher)
  ```

  Add test:
  ```kotlin
  @Test
  fun `isOffline becomes true when network is lost`() = runTest(dispatcher) {
      viewModel.uiState.test {
          awaitItem() // initial

          onlineFlow.emit(false)
          dispatcher.scheduler.advanceUntilIdle()

          val state = awaitItem()
          assertTrue(state.isOffline)
      }
  }
  ```

- [ ] **Step 4: Run all ViewModel tests**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest" 2>&1 | tail -20
  ```

  Expected: all tests pass including the new offline test.

- [ ] **Step 5: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
          app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
  git commit -m "feat(android): ChatViewModel 接入 NetworkMonitor 和 ProcessLifecycle 实现离线检测与自动重连

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 3: Show offline banner in `ChatScreen`

**Problem:** `isOffline` field is now set correctly but nothing in the UI reads it.

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`

- [ ] **Step 1: Add offline banner to `ChatScreen`**

  Add import:
  ```kotlin
  import androidx.compose.animation.AnimatedVisibility
  import androidx.compose.foundation.background
  import androidx.compose.foundation.layout.fillMaxWidth
  import androidx.compose.material3.MaterialTheme
  import androidx.compose.ui.text.style.TextAlign
  import androidx.compose.ui.unit.dp
  import androidx.compose.foundation.layout.Box
  ```

  In the detail pane `Column` (after `Modifier.fillMaxSize().padding(innerPadding).imePadding()`), insert before `MessageList`:

  ```kotlin
  AnimatedVisibility(visible = chatState.isOffline) {
      Box(
          modifier = Modifier
              .fillMaxWidth()
              .background(MaterialTheme.colorScheme.errorContainer)
              .padding(vertical = 4.dp),
          contentAlignment = androidx.compose.ui.Alignment.Center,
      ) {
          Text(
              text = "网络已断开，重连中…",
              style = MaterialTheme.typography.labelMedium,
              color = MaterialTheme.colorScheme.onErrorContainer,
              textAlign = TextAlign.Center,
          )
      }
  }
  ```

- [ ] **Step 2: Verify build**

  ```bash
  cd ui/mobile-android
  ./gradlew :app:compileDebugKotlin 2>&1 | tail -10
  ```

  Expected: `BUILD SUCCESSFUL`

- [ ] **Step 3: Run all unit tests**

  ```bash
  ./gradlew :app:testDebugUnitTest 2>&1 | tail -10
  ```

  Expected: all pass.

- [ ] **Step 4: Commit**

  ```bash
  git add app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
  git commit -m "feat(android): 离线时 ChatScreen 顶部显示断网 Banner

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```
