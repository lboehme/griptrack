// Root build file. Plugin versions are declared here (with apply false) and
// applied in app/build.gradle.kts, per the standard Gradle plugins-DSL
// convention.
//
// Pinned versions and sources (see docs/android-feasibility.md for the full
// rationale):
//   - Android Gradle Plugin 8.7.0 — requires Gradle 8.9, JDK 17.
//     https://developer.android.com/build/releases/agp-8-7-0-release-notes
//   - Chaquopy 17.0.0 (2025-12-01) — supports AGP 7.3-9.2, Python 3.10-3.14.
//     https://chaquo.com/chaquopy/doc/current/versions.html
//     https://chaquo.com/chaquopy/doc/current/changelog.html
plugins {
    id("com.android.application") version "8.7.0" apply false
    id("com.chaquo.python") version "17.0.0" apply false
}
