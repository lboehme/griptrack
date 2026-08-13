// GripTrack Android shell (#97) — Chaquopy feasibility skeleton.
//
// See android/README.md and docs/android-feasibility.md for what this project
// proves, the pinned versions, and the go/no-go criteria.

pluginManagement {
    repositories {
        // Chaquopy 17.x is published to Maven Central (no separate chaquo.com
        // maven repo needed, unlike pre-15.x versions). Source:
        // https://chaquo.com/chaquopy/doc/current/android.html
        gradlePluginPortal()
        google()
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "griptrack-android"
include(":app")
