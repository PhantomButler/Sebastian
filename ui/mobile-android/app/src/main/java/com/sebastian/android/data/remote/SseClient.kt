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
import com.sebastian.android.di.SseOkHttp
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
    @SseOkHttp private val okHttpClient: OkHttpClient,
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
