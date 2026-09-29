import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Ключ подписи релиза — только вне репозитория (ТЗ 3.4: без ключей в git).
// Берётся из android/key.properties (в .gitignore) или из переменных
// окружения CI: FINNY_KEYSTORE, FINNY_KEYSTORE_PASSWORD, FINNY_KEY_ALIAS,
// FINNY_KEY_PASSWORD. Нет ключа — релиз подписывается debug-ключом,
// чтобы сборка работала у любого разработчика.
val keyProps = Properties().apply {
    val file = rootProject.file("key.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

fun signingValue(prop: String, env: String): String? =
    keyProps.getProperty(prop) ?: System.getenv(env)?.takeIf { it.isNotBlank() }

val releaseStore = signingValue("storeFile", "FINNY_KEYSTORE")

android {
    namespace = "ru.litenergy.finny"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // Уникальное имя пакета для RuStore (ТЗ 3.3).
        applicationId = "ru.litenergy.finny"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Версия и номер сборки — из pubspec.yaml (version: X.Y.Z+N).
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (releaseStore != null) {
            create("release") {
                storeFile = file(releaseStore)
                storePassword = signingValue("storePassword", "FINNY_KEYSTORE_PASSWORD")
                keyAlias = signingValue("keyAlias", "FINNY_KEY_ALIAS")
                keyPassword = signingValue("keyPassword", "FINNY_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (releaseStore != null) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
