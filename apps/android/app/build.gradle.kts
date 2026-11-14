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
    }

    // Reuse exactly the responsive web app rather than an independent UI.
    // Relative to apps/android/app, ../../web resolves to apps/web.
    sourceSets.getByName("main").assets.srcDir(file("../../web"))
}
