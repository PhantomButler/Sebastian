package com.sebastian.android.di

import com.sebastian.android.BuildConfig
import com.sebastian.android.data.local.SecureTokenStore
import com.sebastian.android.data.local.SettingsDataStore
import com.sebastian.android.data.remote.ApiService
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides @Singleton
    fun provideMoshi(): Moshi = Moshi.Builder()
        // KotlinJsonAdapterFactory required for Map<String, Any> deserialization
        // used by getAgents(), getPendingApprovals(), and health() in ApiService
        .addLast(KotlinJsonAdapterFactory())
        .build()

    @Provides @Singleton
    fun provideOkHttpClient(
        tokenStore: SecureTokenStore,
        settingsDataStore: SettingsDataStore,
    ): OkHttpClient {
        val authInterceptor = Interceptor { chain ->
            val token = tokenStore.getToken()
            val req = if (token != null) {
                chain.request().newBuilder()
                    .header("Authorization", "Bearer $token")
                    .build()
            } else chain.request()
            chain.proceed(req)
        }

        // 动态 BaseUrl：每次请求从 DataStore 读取最新 serverUrl 替换
        val baseUrlInterceptor = Interceptor { chain ->
            val serverUrl = runBlocking { settingsDataStore.serverUrl.first() }.trimEnd('/')
            val original = chain.request()
            if (serverUrl.isEmpty()) return@Interceptor chain.proceed(original)
            val base = okhttp3.HttpUrl.parse("$serverUrl/")
                ?: return@Interceptor chain.proceed(original)
            val newUrl = original.url.newBuilder()
                .scheme(base.scheme())
                .host(base.host())
                .port(base.port())
                .build()
            chain.proceed(original.newBuilder().url(newUrl).build())
        }

        val logging = HttpLoggingInterceptor().apply {
            level = if (BuildConfig.DEBUG) HttpLoggingInterceptor.Level.BASIC
                    else HttpLoggingInterceptor.Level.NONE
        }

        return OkHttpClient.Builder()
            .addInterceptor(baseUrlInterceptor)
            .addInterceptor(authInterceptor)
            .addInterceptor(logging)
            .build()
    }

    @Provides @Singleton
    fun provideRetrofit(okHttpClient: OkHttpClient, moshi: Moshi): Retrofit =
        Retrofit.Builder()
            .client(okHttpClient)
            .baseUrl("http://placeholder.local/")   // 运行时由 baseUrlInterceptor 替换
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()

    @Provides @Singleton
    fun provideApiService(retrofit: Retrofit): ApiService =
        retrofit.create(ApiService::class.java)
}
