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
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Qualifier
import javax.inject.Singleton

@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class SseOkHttp

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
    ): OkHttpClient = buildBaseOkHttpClient(tokenStore, settingsDataStore).build()

    @Provides @Singleton
    @SseOkHttp
    fun provideSseOkHttpClient(
        tokenStore: SecureTokenStore,
        settingsDataStore: SettingsDataStore,
    ): OkHttpClient = buildBaseOkHttpClient(tokenStore, settingsDataStore)
        .readTimeout(0, TimeUnit.SECONDS)   // SSE 长连接，禁用读超时
        .build()

    private fun buildBaseOkHttpClient(
        tokenStore: SecureTokenStore,
        settingsDataStore: SettingsDataStore,
    ): OkHttpClient.Builder {
        val authInterceptor = Interceptor { chain ->
            val token = tokenStore.getToken()
            val req = if (token != null) {
                chain.request().newBuilder()
                    .header("Authorization", "Bearer $token")
                    .build()
            } else chain.request()
            chain.proceed(req)
        }

        val baseUrlInterceptor = Interceptor { chain ->
            val serverUrl = settingsDataStore.serverUrl.value.trimEnd('/')
            val original = chain.request()
            if (serverUrl.isEmpty()) return@Interceptor chain.proceed(original)
            val base = "$serverUrl/".toHttpUrlOrNull()
                ?: return@Interceptor chain.proceed(original)
            val newUrl = original.url.newBuilder()
                .scheme(base.scheme)
                .host(base.host)
                .port(base.port)
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
