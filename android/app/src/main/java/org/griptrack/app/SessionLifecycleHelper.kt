package org.griptrack.app

/**
 * Pure navigation and lifecycle logic for the GripTrack Android shell (#140, §2.3, §2.4).
 *
 * Encapsulates session restoration rules across Activity recreation and process death,
 * path normalization, tab root detection, and Back navigation state handling.
 */
object SessionLifecycleHelper {

    const val PREFS_NAME = "griptrack_prefs"
    const val KEY_SAVED_PATH = "saved_path"
    const val KEY_SAVED_TIME = "saved_time"
    const val SESSION_RESTORE_TIMEOUT_MS = 3 * 3600 * 1000L // 3 hours

    const val HOME_PATH = "/"

    val TAB_ROOTS = setOf(
        "/session/new",
        "/dashboard",
        "/climbs",
        "/profile"
    )

    val NON_RESTORABLE_SESSION_PATHS = setOf(
        "/session/new",
        "/session/create",
        "/session/workset",
        "/session/set",
        "/session/set/delete",
        "/session/set/restore",
        "/session/workset/delete",
        "/session/estimate",
        "/session/check",
        "/session/update",
        "/session/pain-report"
    )

    /**
     * Extracts relative path and query for loopback/same-origin URLs.
     * Returns null for external domains.
     */
    fun extractPathAndQuery(url: String?, loopbackHost: String = "127.0.0.1", port: Int = 8000): String? {
        if (url.isNullOrBlank()) return null
        val loopbackPrefixes = listOf(
            "http://$loopbackHost:$port",
            "http://localhost:$port"
        )
        for (prefix in loopbackPrefixes) {
            if (url.startsWith(prefix)) {
                val relative = url.removePrefix(prefix)
                return if (relative.isEmpty() || !relative.startsWith("/")) {
                    "/$relative"
                } else {
                    relative
                }
            }
        }
        if (url.startsWith("/")) {
            return url
        }
        return null
    }

    /**
     * Normalizes a full or relative URL into a clean pathname (e.g. "/dashboard").
     */
    fun normalizePath(url: String?, loopbackHost: String = "127.0.0.1", port: Int = 8000): String {
        val pathAndQuery = extractPathAndQuery(url, loopbackHost, port) ?: return HOME_PATH
        val pathWithoutQuery = pathAndQuery.substringBefore('?').substringBefore('#')
        val trimmed = pathWithoutQuery.trimEnd('/')
        return if (trimmed.isEmpty()) HOME_PATH else trimmed
    }

    /**
     * Determines whether a saved path represents an active session that should be restored
     * on process resurrection or recreation.
     *
     * Only active `/session/...` pages (e.g. warmup, worksets) are restored.
     * Tab roots like `/session/new`, auth pages, and POST actions are rejected.
     */
    fun isRestorableSessionPath(pathAndQuery: String?): Boolean {
        if (pathAndQuery.isNullOrBlank()) return false
        val path = normalizePath(pathAndQuery)

        if (!path.startsWith("/session/")) return false
        if (path == "/login" || path == "/register") return false
        if (NON_RESTORABLE_SESSION_PATHS.contains(path)) return false

        return true
    }

    /**
     * Checks if a session path was saved recently enough to resume (within 3 hours).
     */
    fun isRecentlySaved(savedTime: Long, currentTimeMs: Long = System.currentTimeMillis()): Boolean {
        if (savedTime <= 0L) return false
        val elapsed = currentTimeMs - savedTime
        return elapsed in 0 until SESSION_RESTORE_TIMEOUT_MS
    }

    /**
     * Identifies whether the given URL is the app Home root ("/").
     */
    fun isHomePage(url: String?): Boolean {
        return normalizePath(url) == HOME_PATH
    }

    /**
     * Identifies whether the given URL is a designated tab root.
     */
    fun isTabRoot(url: String?): Boolean {
        val path = normalizePath(url)
        return path == HOME_PATH || TAB_ROOTS.contains(path)
    }
}
