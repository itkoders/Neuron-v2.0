plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "uz.itkoders.neyron.sms"
    compileSdk = 35
    defaultConfig {
        applicationId = "uz.itkoders.neyron.sms"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
    }
    buildFeatures { buildConfig = true }
    buildTypes {
        debug { buildConfigField("String", "API_BASE_URL", "\"https://neuron-v2.onrender.com\"") }
        release {
            isMinifyEnabled = false
            buildConfigField("String", "API_BASE_URL", "\"https://neuron-v2.onrender.com\"")
        }
    }
}
dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
}
