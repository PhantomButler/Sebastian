package com.sebastian.android.di

import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

// SettingsDataStore 和 SecureTokenStore 均使用 @Inject constructor + @Singleton
// 无需在此手动提供，Hilt 自动处理。
// 如果将来引入接口抽象，在此添加 @Binds。
@Module
@InstallIn(SingletonComponent::class)
object StorageModule
