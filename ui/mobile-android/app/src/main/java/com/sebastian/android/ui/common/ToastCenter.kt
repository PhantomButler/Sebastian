package com.sebastian.android.ui.common

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.widget.Toast
import androidx.annotation.VisibleForTesting

object ToastCenter {
    private val lock = Any()
    private val lastShownAt = HashMap<String, Long>()
    private var currentToast: Toast? = null

    @Volatile @VisibleForTesting internal var clock: () -> Long = { SystemClock.uptimeMillis() }
    @Volatile @VisibleForTesting internal var mainExecutor: (Runnable) -> Unit =
        { Handler(Looper.getMainLooper()).post(it) }
    @Volatile @VisibleForTesting internal var toastFactory: (Context, CharSequence, Int) -> Toast =
        { ctx, msg, dur -> Toast.makeText(ctx, msg, dur) }

    fun show(
        context: Context,
        message: CharSequence,
        key: String = message.toString(),
        throttleMs: Long = 1500L,
        duration: Int = Toast.LENGTH_SHORT,
    ) {
        val now = clock()
        synchronized(lock) {
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
        synchronized(lock) {
            lastShownAt.clear()
            currentToast = null
        }
    }
}
