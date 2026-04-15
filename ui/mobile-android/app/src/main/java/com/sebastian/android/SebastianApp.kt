package com.sebastian.android

import android.app.Application
import com.sebastian.android.notification.NotificationChannels
import com.sebastian.android.notification.NotificationDispatcher
import dagger.hilt.android.HiltAndroidApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import javax.inject.Inject

@HiltAndroidApp
class SebastianApp : Application() {
    @Inject lateinit var notificationDispatcher: NotificationDispatcher

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()
        NotificationChannels.registerAll(this)
        notificationDispatcher.start(appScope)
    }
}
