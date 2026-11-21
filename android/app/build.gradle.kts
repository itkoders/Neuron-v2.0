plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val neuronBaseUrl = providers.gradleProperty("NEURON_BASE_URL")
    .orElse(providers.environmentVariable("NEURON_BASE_URL"))
    .orElse("https://example.invalid")
    .get()

android {
    namespace = "uz.itkoders.neuron"
    compileSdk = 35

    defaultConfig {
        applicationId = "uz.itkoders.neuron"
        minSdk = 23
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
        buildConfigField("String", "NEURON_BASE_URL", "\"$neuronBaseUrl\"")
    }

    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
