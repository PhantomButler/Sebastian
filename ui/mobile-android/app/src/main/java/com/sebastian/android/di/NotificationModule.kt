package com.sebastian.android.di

import com.sebastian.android.notification.AndroidNotificationSink
import com.sebastian.android.notification.NotificationSink
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class NotificationModule {
    @Binds
    @Singleton
    abstract fun bindNotificationSink(impl: AndroidNotificationSink): NotificationSink
}
