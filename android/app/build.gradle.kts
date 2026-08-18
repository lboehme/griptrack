// GripTrack Android shell — app module (#98).
//
// Packages the embedded FastAPI backend, Jinja templates, static assets, and
// migrations via Chaquopy on CPython 3.13, and embeds them behind a native
// WebView on Android arm64.

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "org.griptrack.app"

    compileSdk = 35

    defaultConfig {
        applicationId = "org.griptrack.app"

        // Chaquopy 17.0 requires minSdk >= 24.
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        // Embedded arm64-v8a target (matches PRD #93).
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

val syncPythonSources by tasks.registering(Sync::class) {
    from(rootDir.resolve("../backend")) {
        into("backend")
        exclude("**/__pycache__/**", "**/*.pyc")
    }
    from(rootDir.resolve("../migrations")) {
        into("migrations")
        exclude("**/__pycache__/**", "**/*.pyc")
    }
    into(layout.buildDirectory.dir("generated/python"))
}

tasks.configureEach {
    if (name != "syncPythonSources" && name.contains("Python")) {
        dependsOn(syncPythonSources)
    }
}

tasks.named("preBuild") {
    dependsOn(syncPythonSources)
}

chaquopy {
    defaultConfig {
        // Chaquopy 17.0 runtime CPython 3.13 (matches cibuildwheel Android wheels).
        version = "3.13"

        val homebrewPython = file("/opt/homebrew/bin/python3.13")
        if (homebrewPython.exists()) {
            buildPython(homebrewPython.absolutePath)
        }

        pip {
            val localWheelsDir = file("wheels")
            val userWheelhouseDir = file("${System.getProperty("user.home")}/griptrack-android-wheels/wheelhouse")
            if (localWheelsDir.exists()) {
                options("--find-links", localWheelsDir.absolutePath)
            }
            if (userWheelhouseDir.exists()) {
                options("--find-links", userWheelhouseDir.absolutePath)
            }

            // Runtime dependencies matching requirements.txt
            install("fastapi==0.139.0")
            install("uvicorn==0.49.0")
            install("pydantic==2.13.4")
            install("sqlmodel==0.0.39")
            install("alembic==1.18.5")
            install("python-multipart==0.0.32")
            install("jinja2==3.1.6")
            install("itsdangerous==2.2.0")
        }

        // Package extraction for runtime disk reads: Jinja templates,
        // static assets, and Alembic migration scripts.
        extractPackages("backend", "migrations")
    }

    sourceSets {
        getByName("main") {
            srcDirs("src/main/python", layout.buildDirectory.dir("generated/python"))
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("com.google.android.material:material:1.12.0")
}
