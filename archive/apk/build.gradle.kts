// Same proven toolchain as the glass-companion (builds on this machine).
plugins {
    id("com.android.application") version "8.7.2" apply false
    id("org.jetbrains.kotlin.android") version "2.2.0" apply false
    // Kotlin 2.x ships the Compose compiler as a plugin (composeOptions is 1.x only)
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.0" apply false
    // FCM: reads app/google-services.json (gitignored publisher credential)
    id("com.google.gms.google-services") version "4.4.2" apply false
}
