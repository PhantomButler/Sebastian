package com.sebastian.android.viewmodel

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import com.sebastian.android.data.local.NetworkMonitor
import com.sebastian.android.data.model.AgentBinding
import com.sebastian.android.data.model.AttachmentKind
import com.sebastian.android.data.model.AttachmentUploadState
import com.sebastian.android.data.model.ModelInputCapabilities
import com.sebastian.android.data.model.PendingAttachment
import com.sebastian.android.data.model.ResolvedBinding
import com.sebastian.android.data.remote.SseEnvelope
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SessionRepository
import com.sebastian.android.data.repository.SettingsRepository
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.After
import org.junit.Before
import org.junit.Test
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.mockito.kotlin.any
import org.mockito.kotlin.anyOrNull
import org.mockito.kotlin.mock
import org.mockito.kotlin.verify
import org.mockito.kotlin.whenever
import java.util.UUID

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelAttachmentTest {

    private lateinit var chatRepository: ChatRepository
    private lateinit var sessionRepository: SessionRepository
    private lateinit var settingsRepository: SettingsRepository
    private lateinit var agentRepository: AgentRepository
    private lateinit var networkMonitor: NetworkMonitor
    private lateinit var viewModel: ChatViewModel
    private lateinit var appContext: Context
    private val dispatcher = StandardTestDispatcher()
    private val sseFlow = MutableSharedFlow<SseEnvelope>(extraBufferCapacity = 64)
    private val serverUrlFlow = MutableStateFlow("http://test.local:8823")
    private val onlineFlow = MutableStateFlow(true)

    @Before
    fun setup() {
        Dispatchers.setMain(dispatcher)
        chatRepository = mock()
        sessionRepository = mock()
        settingsRepository = mock()
        agentRepository = mock()
        networkMonitor = mock()
        appContext = mock()
        val contentResolver: ContentResolver = mock()
        whenever(appContext.contentResolver).thenReturn(contentResolver)
        whenever(networkMonitor.isOnline).thenReturn(onlineFlow)
        whenever(settingsRepository.serverUrl).thenReturn(serverUrlFlow)
        whenever(chatRepository.sessionStream(any(), any(), anyOrNull())).thenReturn(sseFlow)
        whenever(chatRepository.globalStream(any(), any())).thenReturn(flowOf())
        runBlocking {
            whenever(chatRepository.sendTurn(any(), any(), any())).thenReturn(Result.success("s1"))
            whenever(chatRepository.cancelTurn(any())).thenReturn(Result.success(Unit))
            whenever(chatRepository.getMessages(any())).thenReturn(Result.success(emptyList()))
            whenever(chatRepository.getTodos(any())).thenReturn(Result.success(emptyList()))
        }
        viewModel = ChatViewModel(appContext, chatRepository, sessionRepository, settingsRepository, agentRepository, networkMonitor, dispatcher)
        viewModel.clock = { dispatcher.scheduler.currentTime }
        dispatcher.scheduler.advanceTimeBy(200)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun vmTest(testBody: suspend TestScope.() -> Unit) = runTest(dispatcher) {
        try {
            testBody()
        } finally {
            viewModel.viewModelScope.cancel()
        }
    }

    private fun makeUri(): Uri = mock<Uri>().also {
        whenever(it.toString()).thenReturn("content://test/file")
        whenever(it.lastPathSegment).thenReturn("file")
    }

    // ── Test 1 ─────────────────────────────────────────────────────────────────

    @Test
    fun `onAttachmentMenuImageSelected emits RequestImagePicker when supportsImageInput is true`() = vmTest {
        viewModel.setInputCapabilities(ModelInputCapabilities(supportsImageInput = true))

        val effects = mutableListOf<ChatUiEffect>()
        val job = launch { viewModel.uiEffects.collect { effects.add(it) } }

        viewModel.onAttachmentMenuImageSelected()
        dispatcher.scheduler.advanceTimeBy(100)

        assertTrue("Must emit RequestImagePicker", effects.any { it is ChatUiEffect.RequestImagePicker })
        assertFalse(
            "Must NOT emit ShowToast",
            effects.any { it is ChatUiEffect.ShowToast },
        )

        job.cancel()
    }

    // ── Test 2 ─────────────────────────────────────────────────────────────────

    @Test
    fun `onAttachmentMenuImageSelected shows toast when supportsImageInput is false`() = vmTest {
        // Default ModelInputCapabilities has supportsImageInput = false
        viewModel.setInputCapabilities(ModelInputCapabilities(supportsImageInput = false))

        val effects = mutableListOf<ChatUiEffect>()
        val job = launch { viewModel.uiEffects.collect { effects.add(it) } }

        viewModel.onAttachmentMenuImageSelected()
        dispatcher.scheduler.advanceTimeBy(100)

        assertTrue(
            "Must emit ShowToast about 不支持图片输入",
            effects.any { it is ChatUiEffect.ShowToast && (it as ChatUiEffect.ShowToast).message.contains("不支持图片") },
        )
        assertFalse(
            "Must NOT emit RequestImagePicker",
            effects.any { it is ChatUiEffect.RequestImagePicker },
        )

        job.cancel()
    }

    // ── Test 3 ─────────────────────────────────────────────────────────────────

    @Test
    fun `sendMessage with attached Uploaded PendingAttachment passes attachmentIds to repository`() = vmTest {
        val uploadedAtt = PendingAttachment(
            localId = UUID.randomUUID().toString(),
            kind = AttachmentKind.IMAGE,
            uri = makeUri(),
            filename = "photo.jpg",
            mimeType = "image/jpeg",
            sizeBytes = 1024L,
            uploadState = AttachmentUploadState.Uploaded("att_1"),
        )
        // Inject pre-uploaded attachment into state
        viewModel.setTestPendingAttachments(listOf(uploadedAtt))

        viewModel.sendMessage("")  // empty text, has attachment
        dispatcher.scheduler.advanceTimeBy(200)

        runBlocking {
            verify(chatRepository).sendTurn(anyOrNull(), any(), org.mockito.kotlin.eq(listOf("att_1")))
        }
    }

    // ── Test 4 ─────────────────────────────────────────────────────────────────

    @Test
    fun `onAttachmentFilePicked rejects unsupported extension`() = vmTest {
        val effects = mutableListOf<ChatUiEffect>()
        val job = launch { viewModel.uiEffects.collect { effects.add(it) } }

        viewModel.onAttachmentFilePicked(makeUri(), "report.pdf", "application/pdf", 100L)
        dispatcher.scheduler.advanceTimeBy(100)

        assertTrue(
            "Must emit ShowToast for unsupported format",
            effects.any { it is ChatUiEffect.ShowToast },
        )
        assertTrue(
            "pendingAttachments must remain empty",
            viewModel.uiState.value.pendingAttachments.isEmpty(),
        )

        job.cancel()
    }

    // ── Test 5 ─────────────────────────────────────────────────────────────────

    @Test
    fun `adding 6th attachment shows toast and keeps count at 5`() = vmTest {
        // Set supportsTextFileInput = true (default), add 5 valid attachments
        viewModel.setInputCapabilities(ModelInputCapabilities(supportsTextFileInput = true))

        repeat(5) { i ->
            viewModel.onAttachmentFilePicked(makeUri(), "file$i.txt", "text/plain", 100L)
        }
        dispatcher.scheduler.advanceTimeBy(100)
        assertEquals(5, viewModel.uiState.value.pendingAttachments.size)

        val effects = mutableListOf<ChatUiEffect>()
        val job = launch { viewModel.uiEffects.collect { effects.add(it) } }

        viewModel.onAttachmentFilePicked(makeUri(), "sixth.txt", "text/plain", 100L)
        dispatcher.scheduler.advanceTimeBy(100)

        assertTrue(
            "Must emit ShowToast about max 5",
            effects.any {
                it is ChatUiEffect.ShowToast && (it as ChatUiEffect.ShowToast).message.contains("5")
            },
        )
        assertEquals(
            "Count must still be 5 after rejection",
            5,
            viewModel.uiState.value.pendingAttachments.size,
        )

        job.cancel()
    }

    // ── Test 5b ────────────────────────────────────────────────────────────────

    @Test
    fun `sendAgentMessage new session passes uploaded attachment ids to createAgentSession`() = vmTest {
        val uploadedAtt = PendingAttachment(
            localId = UUID.randomUUID().toString(),
            kind = AttachmentKind.IMAGE,
            uri = makeUri(),
            filename = "photo.jpg",
            mimeType = "image/jpeg",
            sizeBytes = 1024L,
            uploadState = AttachmentUploadState.Uploaded("att_1"),
        )
        viewModel.setTestPendingAttachments(listOf(uploadedAtt))
        whenever(sessionRepository.createAgentSession(any(), any(), any(), any())).thenReturn(
            Result.success(com.sebastian.android.data.model.Session(id = "s1", title = "", agentType = "forge")),
        )

        viewModel.sendAgentMessage("forge", "")
        // 200 ms covers the upload step (already-Uploaded attachment returns synchronously) plus
        // the createAgentSession call; matches the pattern used in sendMessage Test 3.
        dispatcher.scheduler.advanceTimeBy(200)

        verify(sessionRepository).createAgentSession(
            org.mockito.kotlin.eq("forge"),
            org.mockito.kotlin.eq(""),
            any(),
            org.mockito.kotlin.eq(listOf("att_1")),
        )
    }

    // ── Test 6 ─────────────────────────────────────────────────────────────────

    @Test
    fun `sendMessage uses explicit attachments argument`() = vmTest {
        val explicit = PendingAttachment(
            localId = UUID.randomUUID().toString(),
            kind = AttachmentKind.TEXT_FILE,
            uri = makeUri(),
            filename = "notes.md",
            mimeType = "text/markdown",
            sizeBytes = 12L,
            uploadState = AttachmentUploadState.Uploaded("att-explicit"),
        )

        viewModel.sendMessage("", attachments = listOf(explicit))
        dispatcher.scheduler.advanceTimeBy(200)

        runBlocking {
            verify(chatRepository).sendTurn(anyOrNull(), any(), org.mockito.kotlin.eq(listOf("att-explicit")))
        }
    }

    // ── Test 6b ────────────────────────────────────────────────────────────────

    @Test
    fun `sendAgentMessage uses explicit attachments argument`() = vmTest {
        val explicit = PendingAttachment(
            localId = UUID.randomUUID().toString(),
            kind = AttachmentKind.TEXT_FILE,
            uri = makeUri(),
            filename = "notes.md",
            mimeType = "text/markdown",
            sizeBytes = 12L,
            uploadState = AttachmentUploadState.Uploaded("att-agent-explicit"),
        )
        whenever(sessionRepository.createAgentSession(any(), anyOrNull(), anyOrNull(), any()))
            .thenReturn(Result.success(com.sebastian.android.data.model.Session(id = "s1", title = "", agentType = "forge")))

        viewModel.sendAgentMessage("forge", "", attachments = listOf(explicit))
        dispatcher.scheduler.advanceTimeBy(200)

        verify(sessionRepository).createAgentSession(
            org.mockito.kotlin.eq("forge"),
            org.mockito.kotlin.eq(""),
            any(),
            org.mockito.kotlin.eq(listOf("att-agent-explicit")),
        )
    }

    // ── Test 7 ─────────────────────────────────────────────────────────────────

    @Test
    fun `refreshInputCapabilities loads default resolved capabilities for main chat`() = vmTest {
        whenever(settingsRepository.getDefaultBinding()).thenReturn(
            Result.success(
                AgentBinding(
                    agentType = "__default__",
                    accountId = "acc-1",
                    modelId = "claude-opus",
                    thinkingEffort = null,
                    resolved = ResolvedBinding(
                        accountName = "Anthropic",
                        providerDisplayName = "Anthropic",
                        modelDisplayName = "Claude",
                        contextWindowTokens = 200000,
                        thinkingCapability = null,
                        supportsImageInput = true,
                        supportsTextFileInput = true,
                    ),
                ),
            ),
        )

        viewModel.refreshInputCapabilities(agentId = null)
        // runCurrent() not advanceUntilIdle(): startDeltaFlusher has an infinite while(true)+delay loop;
        // advanceUntilIdle() would never terminate. runCurrent() flushes only tasks queued at the
        // current virtual time, which is enough for this single-step coroutine body.
        dispatcher.scheduler.runCurrent()

        assertTrue(viewModel.uiState.value.inputCapabilities.supportsImageInput)
        assertTrue(viewModel.uiState.value.inputCapabilities.supportsTextFileInput)
    }

    // ── Test 8 ─────────────────────────────────────────────────────────────────

    @Test
    fun `refreshInputCapabilities loads agent resolved capabilities for sub agent`() = vmTest {
        whenever(agentRepository.getAgentBinding("forge")).thenReturn(
            Result.success(
                AgentBinding(
                    agentType = "forge",
                    accountId = "acc-1",
                    modelId = "vision-model",
                    thinkingEffort = null,
                    resolved = ResolvedBinding(
                        accountName = "Provider",
                        providerDisplayName = "Provider",
                        modelDisplayName = "Vision",
                        contextWindowTokens = 128000,
                        thinkingCapability = null,
                        supportsImageInput = true,
                        supportsTextFileInput = false,
                    ),
                ),
            ),
        )

        viewModel.refreshInputCapabilities(agentId = "forge")
        // Same reasoning: runCurrent() avoids the advanceUntilIdle() infinite-loop issue.
        dispatcher.scheduler.runCurrent()

        assertTrue(viewModel.uiState.value.inputCapabilities.supportsImageInput)
        assertFalse(viewModel.uiState.value.inputCapabilities.supportsTextFileInput)
    }
}
