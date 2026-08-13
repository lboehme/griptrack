// GripTrack Android shell — app module.
//
// THIS TICKET (#97) SCOPE: prove that bcrypt and pydantic-core install and
// run under Chaquopy on Python 3.12 / arm64-v8a. The pip{} block below is
// deliberately minimal — just the two feasibility targets, not the full
// backend/requirements.txt. Embedding the actual FastAPI backend is #98.
//
// See docs/android-feasibility.md for the pinned-version rationale and the
// go/no-go criteria this build is meant to answer.

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android") version "2.0.21"
    id("com.chaquo.python")
}

android {
    namespace = "org.griptrack.app"

    // compileSdk/targetSdk 35 (Android 15) is current-stable as of AGP 8.7;
    // AGP 8.7 supports up to API 35.
    // https://developer.android.com/build/releases/agp-8-7-0-release-notes
    compileSdk = 35

    defaultConfig {
        applicationId = "org.griptrack.app"

        // Chaquopy 17.0 requires minSdk >= 24.
        // https://chaquo.com/chaquopy/doc/current/versions.html
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-feasibility"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Feasibility scope is arm64 only — that's the real device ABI this
        // ticket needs to prove (per #97/#93: "targeting an arm64 APK").
        // x86_64 is deliberately NOT included: it would let the emulator
        // paper over an arm64-specific wheel-availability problem, which is
        // exactly the risk this ticket exists to surface.
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

chaquopy {
    defaultConfig {
        // Python 3.12 — matches backend/ (see repo-root CLAUDE.md: "Target
        // Python 3.12 (matches the project)" in PRD #93) and is within
        // Chaquopy 17.0's supported range (3.10-3.14, runtime 3.12.12).
        // https://chaquo.com/chaquopy/doc/current/versions.html
        version = "3.12"

        pip {
            // --- Feasibility targets for #97 ---
            // Pinned to the exact versions backend/requirements.txt pins
            // today, so this is a real test of the versions the app would
            // actually ship, not a softer stand-in:
            //   requirements.txt: bcrypt==5.0.0
            install("bcrypt==5.0.0")
            //   requirements.txt: pydantic==2.13.4, which depends on
            //   pydantic-core==2.46.4 exactly (checked via PyPI metadata).
            install("pydantic-core==2.46.4")

            // KNOWN RISK (see docs/android-feasibility.md): as of this
            // writing, Chaquopy's own prebuilt-wheel repository
            // (chaquo.com/pypi-13.1/) hosts bcrypt only up to 3.2.2 — the
            // last version BEFORE bcrypt's 4.0 rewrite from C to Rust — and
            // has no pydantic-core entry at all. This pip block may
            // therefore fail to resolve at Gradle build time; that failure
            // IS a valid (negative) answer to this ticket's feasibility
            // question, not a project misconfiguration. See the doc for the
            // fallback probe (pin bcrypt==3.2.2) and remediation paths.
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
}
