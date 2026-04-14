# Add project specific ProGuard rules here.

# Moshi
-keepclassmembers class ** {
    @com.squareup.moshi.* <fields>;
}
-keep @com.squareup.moshi.JsonClass class * { *; }

# Retrofit
-keepattributes Signature, InnerClasses, EnclosingMethod
-keepattributes RuntimeVisibleAnnotations, RuntimeVisibleParameterAnnotations
-keepclassmembers,allowshrinking,allowobfuscation interface * {
    @retrofit2.http.* <methods>;
}

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
