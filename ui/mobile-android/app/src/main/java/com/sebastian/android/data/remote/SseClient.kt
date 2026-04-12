package com.sebastian.android.data.remote

import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.dto.SseFrameParser
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
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
     * 订阅单 session 事件流。
     * lastEventId: 断线重连时传入，null 表示新连接
     */
    fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String? = null): Flow<StreamEvent> =
        sseFlow("$baseUrl/api/v1/sessions/$sessionId/stream", lastEventId)

    /**
     * 订阅全局事件流（task, approval 等）
     */
    fun globalStream(baseUrl: String, lastEventId: String? = null): Flow<StreamEvent> =
        sseFlow("$baseUrl/api/v1/stream", lastEventId)

    private fun sseFlow(url: String, lastEventId: String?): Flow<StreamEvent> = callbackFlow {
        val requestBuilder = Request.Builder().url(url)
        lastEventId?.let { requestBuilder.header("Last-Event-Id", it) }
        val request = requestBuilder.build()

        val listener = object : EventSourceListener() {
            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                val event = SseFrameParser.parse(data)
                trySend(event)
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
}
