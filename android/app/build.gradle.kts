// AGP 9 compiles Kotlin itself (built-in Kotlin), no kotlin-android plugin needed.
plugins {
    id("com.android.application")
}

android {
    namespace = "dev.healthagent.sync"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.healthagent.sync"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("androidx.health.connect:connect-client:1.1.0")
    implementation("androidx.work:work-runtime-ktx:2.11.2")
    implementation("androidx.activity:activity-ktx:1.13.0")
    implementation("androidx.core:core-ktx:1.18.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.10.0")
}
