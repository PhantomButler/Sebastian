package com.sebastian.android.ui.common

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.widget.Toast
import androidx.annotation.VisibleForTesting

object ToastCenter {
    private val lastShownAt = HashMap<String, Long>()
    private var currentToast: Toast? = null

    @VisibleForTesting internal var clock: () -> Long = { SystemClock.uptimeMillis() }
    @VisibleForTesting internal var mainExecutor: (Runnable) -> Unit =
        { Handler(Looper.getMainLooper()).post(it) }
    @VisibleForTesting internal var toastFactory: (Context, CharSequence, Int) -> Toast =
        { ctx, msg, dur -> Toast.makeText(ctx, msg, dur) }

    fun show(
        context: Context,
        message: CharSequence,
        key: String = message.toString(),
        throttleMs: Long = 1500L,
        duration: Int = Toast.LENGTH_SHORT,
    ) {
        val now = clock()
        synchronized(this) {
            val last = lastShownAt[key]
            if (last != null && now - last < throttleMs) return
            lastShownAt[key] = now
        }
        val app = context.applicationContext
        mainExecutor {
            currentToast?.cancel()
            currentToast = toastFactory(app, message, duration).also { it.show() }
        }
    }

    @VisibleForTesting
    internal fun resetForTest() {
        synchronized(this) {
            lastShownAt.clear()
            currentToast = null
        }
    }
}
