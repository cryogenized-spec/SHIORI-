plugins {
    id("com.android.application")
}

// A stable signing identity is OPTIONAL for disposable debug upgrade rehearsal.
// Never commit signing material or make it a prerequisite of ordinary CI builds.
val stableDevEnvNames = listOf(
    "SHIORI_DEV_KEYSTORE_PATH",
    "SHIORI_DEV_KEYSTORE_PASSWORD",
    "SHIORI_DEV_KEY_ALIAS",
    "SHIORI_DEV_KEY_PASSWORD"
)
val stableDevEnv = stableDevEnvNames.associateWith { key ->
    System.getenv(key)?.takeIf { it.isNotBlank() }
}
val stableDevSigningRequested = stableDevEnv.values.any { it != null }
if (stableDevSigningRequested && stableDevEnv.values.any { it == null }) {
    throw GradleException(
        "Stable SHIORI debug signing needs all four SHIORI_DEV_KEY* variables; " +
            "partial configuration is refused"
    )
}
val versionCodeOverride = System.getenv("SHIORI_DEV_VERSION_CODE")
    ?.takeIf { it.isNotBlank() }
if (versionCodeOverride != null && !stableDevSigningRequested) {
    throw GradleException(
        "SHIORI_DEV_VERSION_CODE requires an explicitly configured stable debug signer"
    )
}
val stableDevVersionCode = versionCodeOverride?.let { raw ->
    raw.toIntOrNull()?.takeIf { it >= 5 }
        ?: throw GradleException("SHIORI_DEV_VERSION_CODE must be an integer >= 5")
} ?: 5

android {
    namespace = "dev.cryogenized.shiori"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.cryogenized.shiori"
        minSdk = 26
        targetSdk = 35
        versionCode = stableDevVersionCode
        versionName = "0.1.4-dev"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        if (stableDevSigningRequested) {
            create("stableDevDebug") {
                val keystore = file(stableDevEnv.getValue("SHIORI_DEV_KEYSTORE_PATH")!!)
                    .canonicalFile
                val repositoryRoot = rootProject.projectDir.parentFile.parentFile.canonicalFile
                if (!keystore.isFile) {
                    throw GradleException("Stable SHIORI debug keystore does not exist")
                }
                if (keystore.toPath().startsWith(repositoryRoot.toPath())) {
                    throw GradleException(
                        "Stable debug keystore must be outside the SHIORI source repository"
                    )
                }
                storeFile = keystore
                storePassword = stableDevEnv.getValue("SHIORI_DEV_KEYSTORE_PASSWORD")
                keyAlias = stableDevEnv.getValue("SHIORI_DEV_KEY_ALIAS")
                keyPassword = stableDevEnv.getValue("SHIORI_DEV_KEY_PASSWORD")
            }
        }
    }
    buildTypes {
        getByName("debug") {
            if (stableDevSigningRequested) {
                signingConfig = signingConfigs.getByName("stableDevDebug")
            }
        }
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
