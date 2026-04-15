package com.sebastian.android.notification

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ProcessLifecycleOwner
import com.sebastian.android.R
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.GlobalSseDispatcher
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton

data class NotificationSpec(
    val channelId: String,
    val title: String,
    val body: String,
    val sessionId: String?,
)

interface NotificationSink {
    fun notify(id: Int, spec: NotificationSpec)
    fun cancel(id: Int)
}

@Singleton
class NotificationDispatcher(
    private val sseDispatcher: GlobalSseDispatcher,
    private val sink: NotificationSink,
    private val foregroundChecker: () -> Boolean,
    private val dispatcher: CoroutineDispatcher,
) {
    @Inject constructor(
        sseDispatcher: GlobalSseDispatcher,
        sink: NotificationSink,
        @param:IoDispatcher dispatcher: CoroutineDispatcher,
    ) : this(
        sseDispatcher = sseDispatcher,
        sink = sink,
        foregroundChecker = {
            ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
        },
        dispatcher = dispatcher,
    )

    private var job: Job? = null

    fun start(scope: CoroutineScope) {
        if (job?.isActive == true) return
        job = scope.launch(dispatcher) {
            sseDispatcher.events.collect { handle(it) }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
    }

    internal fun handle(event: StreamEvent) {
        when (event) {
            is StreamEvent.ApprovalRequested -> {
                if (foregroundChecker()) return
                sink.notify(
                    id = event.approvalId.hashCode(),
                    spec = NotificationSpec(
                        channelId = NotificationChannels.APPROVAL,
                        title = event.toolName,
                        body = event.reason,
                        sessionId = event.sessionId,
                    ),
                )
            }
            is StreamEvent.ApprovalGranted -> sink.cancel(event.approvalId.hashCode())
            is StreamEvent.ApprovalDenied -> sink.cancel(event.approvalId.hashCode())
            is StreamEvent.SessionCompleted -> {
                if (foregroundChecker()) return
                sink.notify(
                    id = event.sessionId.hashCode(),
                    spec = NotificationSpec(
                        channelId = NotificationChannels.TASK_PROGRESS,
                        title = "任务完成",
                        body = event.goal,
                        sessionId = event.sessionId,
                    ),
                )
            }
            is StreamEvent.SessionFailed -> {
                if (foregroundChecker()) return
                sink.notify(
                    id = event.sessionId.hashCode(),
                    spec = NotificationSpec(
                        channelId = NotificationChannels.TASK_PROGRESS,
                        title = "任务失败",
                        body = event.error,
                        sessionId = event.sessionId,
                    ),
                )
            }
            else -> Unit
        }
    }
}

@Singleton
class AndroidNotificationSink @Inject constructor(
    @ApplicationContext private val context: Context,
) : NotificationSink {
    override fun notify(id: Int, spec: NotificationSpec) {
        val manager = NotificationManagerCompat.from(context)
        if (!manager.areNotificationsEnabled()) return

        val builder = NotificationCompat.Builder(context, spec.channelId)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(spec.title)
            .setContentText(spec.body)
            .setAutoCancel(true)
            .setPriority(
                if (spec.channelId == NotificationChannels.APPROVAL) {
                    NotificationCompat.PRIORITY_HIGH
                } else {
                    NotificationCompat.PRIORITY_DEFAULT
                }
            )

        spec.sessionId?.let { sid ->
            val intent = Intent(
                Intent.ACTION_VIEW,
                Uri.parse("sebastian://session/$sid"),
            ).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val pi = PendingIntent.getActivity(
                context,
                sid.hashCode(),
                intent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            builder.setContentIntent(pi)
        }

        try {
            manager.notify(id, builder.build())
        } catch (_: SecurityException) {
            // POST_NOTIFICATIONS 未授予；静默忽略
        }
    }

    override fun cancel(id: Int) {
        NotificationManagerCompat.from(context).cancel(id)
    }
}
