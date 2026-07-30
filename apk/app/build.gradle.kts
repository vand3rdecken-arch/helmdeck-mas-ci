import java.util.Properties
import java.io.FileInputStream

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.gms.google-services")
}

// release signing pulled from apk/keystore.properties (gitignored). Absent on a
// fresh checkout -> release stays unsigned (still builds; just not store-ready).
val keystorePropsFile = rootProject.file("keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) load(FileInputStream(keystorePropsFile))
}
val hasSigning = keystorePropsFile.exists()

android {
    namespace = "app.swarmdeck"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.swarmdeck"
        minSdk = 29
        targetSdk = 34
        versionCode = 24
        versionName = "2.4-glass"
        // required for connectedAndroidTest - without it the device cannot find
        // the instrumentation and the run dies with "Process crashed"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    signingConfigs {
        create("release") {
            if (hasSigning) {
                storeFile = rootProject.file(keystoreProps["storeFile"] as String)
                storePassword = keystoreProps["storePassword"] as String
                keyAlias = keystoreProps["keyAlias"] as String
                keyPassword = keystoreProps["keyPassword"] as String
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            if (hasSigning) signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { viewBinding = true; compose = true }
    packaging { resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" } }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // push: OS-level delivery; payload is NaCl-sealed by the daemon, Google
    // transports ciphertext only (no analytics artifacts pulled in)
    implementation("com.google.firebase:firebase-messaging:24.1.0")
    // The hub holds the secrets (APK rule): pairing + daemon address live in encrypted prefs.
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    // E2EE over the relay: libsodium crypto_box (Curve25519 + XSalsa20-Poly1305),
    // byte-compatible with the daemon's PyNaCl and Paseo's tweetnacl.
    implementation("com.goterl:lazysodium-android:5.1.0@aar")
    implementation("net.java.dev.jna:jna:5.14.0@aar")
    // Compose UI - the phone renders SwarmDeck's own design tokens (ui/Theme.kt)
    // instead of stock Android widgets, so it matches the desktop.
    val composeBom = platform("androidx.compose:compose-bom:2024.09.03")
    implementation(composeBom)
    androidTestImplementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.4")
    // instrumented E2E tests
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
    testImplementation("junit:junit:4.13.2")
}
