package com.sebastian.android.di

import com.sebastian.android.data.local.MarkdownParser
import com.sebastian.android.data.local.MarkwonMarkdownParser
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class MarkdownModule {
    @Binds
    @Singleton
    abstract fun bindMarkdownParser(impl: MarkwonMarkdownParser): MarkdownParser
}
