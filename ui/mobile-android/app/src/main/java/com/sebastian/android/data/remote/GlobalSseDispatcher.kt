package com.sebastian.android.data.remote

import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.IoDispatcher
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlin.coroutines.cancellation.CancellationException
import javax.inject.Inject
import javax.inject.Singleton

enum class ConnectionState { Disconnected, Connecting, Connected }

@Singleton
class GlobalSseDispatcher @Inject constructor(
    private val chatRepository: ChatRepository,
    private val settingsRepository: SettingsRepository,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) {
    private val _events = MutableSharedFlow<StreamEvent>(
        replay = 0,
        extraBufferCapacity = 64,
    )
    val events: SharedFlow<StreamEvent> = _events.asSharedFlow()

    private val _connectionState = MutableStateFlow(ConnectionState.Disconnected)
    val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()

    private var job: Job? = null

    fun start(scope: CoroutineScope) {
        if (job?.isActive == true) return
        job = scope.launch(dispatcher) {
            val baseUrl = settingsRepository.serverUrl.first()
            if (baseUrl.isEmpty()) return@launch
            _connectionState.value = ConnectionState.Connecting
            try {
                chatRepository.globalStream(baseUrl, null)
                    .map { it.event }
                    .collect { event ->
                        if (_connectionState.value != ConnectionState.Connected) {
                            _connectionState.value = ConnectionState.Connected
                        }
                        _events.emit(event)
                    }
            } catch (_: CancellationException) {
                throw CancellationException()
            } catch (_: Exception) {
                // 非致命；下次 start 会重新连接
            } finally {
                _connectionState.value = ConnectionState.Disconnected
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        _connectionState.value = ConnectionState.Disconnected
    }
}
