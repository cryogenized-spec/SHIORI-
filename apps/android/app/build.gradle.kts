plugins {
    id("com.android.application")
}

android {
    namespace = "dev.cryogenized.shiori"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.cryogenized.shiori"
        minSdk = 26
        targetSdk = 35
        versionCode = 5
        versionName = "0.1.4-dev"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    // Reuse exactly the responsive web app rather than an independent UI.
    // Relative to apps/android/app, ../../web resolves to apps/web.
    sourceSets.getByName("main").assets.srcDir(file("../../web"))
}

dependencies {
    // Android runtime UI tests, isolated to the emulator test APK. Neither
    // library is packaged in SHIORI's offline production/debug application.
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test:core:1.6.1")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
