package com.sebastian.android

import android.app.Application
import coil.Coil
import coil.ImageLoader
import com.sebastian.android.notification.NotificationChannels
import com.sebastian.android.notification.NotificationDispatcher
import dagger.hilt.android.HiltAndroidApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import okhttp3.OkHttpClient
import javax.inject.Inject

@HiltAndroidApp
class SebastianApp : Application() {
    @Inject lateinit var notificationDispatcher: NotificationDispatcher
    @Inject lateinit var okHttpClient: OkHttpClient

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()
        NotificationChannels.registerAll(this)
        notificationDispatcher.start(appScope)
        // Coil uses the same OkHttpClient as Retrofit so it carries auth + baseUrl interceptors.
        Coil.setImageLoader(
            ImageLoader.Builder(this).okHttpClient(okHttpClient).build()
        )
    }
}
