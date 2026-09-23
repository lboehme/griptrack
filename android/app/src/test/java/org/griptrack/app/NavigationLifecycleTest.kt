package org.griptrack.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Unit tests for Android shell lifecycle restoration and back navigation logic (#140, §2.3, §2.4).
 */
class NavigationLifecycleTest {

    @Test
    fun testExtractPathAndQuery() {
        assertEquals(
            "/session/worksets?grip_type_id=half_crimp&edge_mm=20",
            SessionLifecycleHelper.extractPathAndQuery("http://127.0.0.1:8000/session/worksets?grip_type_id=half_crimp&edge_mm=20")
        )
        assertEquals("/", SessionLifecycleHelper.extractPathAndQuery("http://127.0.0.1:8000/"))
        assertEquals("/", SessionLifecycleHelper.extractPathAndQuery("http://127.0.0.1:8000"))
        assertEquals("/dashboard", SessionLifecycleHelper.extractPathAndQuery("http://127.0.0.1:8000/dashboard"))
        assertEquals("/session/warmup", SessionLifecycleHelper.extractPathAndQuery("http://localhost:8000/session/warmup"))
        assertEquals("/session/warmup", SessionLifecycleHelper.extractPathAndQuery("/session/warmup"))

        // External URLs should not be treated as same-origin
        assertNull(SessionLifecycleHelper.extractPathAndQuery("https://google.com/search?q=griptrack"))
        assertNull(SessionLifecycleHelper.extractPathAndQuery("http://example.com/foo"))
        assertNull(SessionLifecycleHelper.extractPathAndQuery(null))
        assertNull(SessionLifecycleHelper.extractPathAndQuery(""))
    }

    @Test
    fun testNormalizePath() {
        assertEquals("/", SessionLifecycleHelper.normalizePath("http://127.0.0.1:8000/"))
        assertEquals("/", SessionLifecycleHelper.normalizePath("http://127.0.0.1:8000"))
        assertEquals("/dashboard", SessionLifecycleHelper.normalizePath("http://127.0.0.1:8000/dashboard"))
        assertEquals("/dashboard", SessionLifecycleHelper.normalizePath("http://127.0.0.1:8000/dashboard/"))
        assertEquals(
            "/session/worksets",
            SessionLifecycleHelper.normalizePath("http://127.0.0.1:8000/session/worksets?grip_type_id=1")
        )
        assertEquals("/session/new", SessionLifecycleHelper.normalizePath("http://127.0.0.1:8000/session/new"))
        assertEquals("/session/new", SessionLifecycleHelper.normalizePath("http://127.0.0.1:8000/session/new/"))
        assertEquals("/login", SessionLifecycleHelper.normalizePath("http://127.0.0.1:8000/login"))
        assertEquals("/register", SessionLifecycleHelper.normalizePath("http://127.0.0.1:8000/register"))
        assertEquals("/", SessionLifecycleHelper.normalizePath(null))
        assertEquals("/", SessionLifecycleHelper.normalizePath(""))
    }

    @Test
    fun testIsRestorableSessionPath() {
        // Active session pages are restorable
        assertTrue(SessionLifecycleHelper.isRestorableSessionPath("/session/worksets"))
        assertTrue(
            SessionLifecycleHelper.isRestorableSessionPath("/session/worksets?grip_type_id=half_crimp&edge_mm=20")
        )
        assertTrue(SessionLifecycleHelper.isRestorableSessionPath("/session/warmup"))
        assertTrue(
            SessionLifecycleHelper.isRestorableSessionPath("/session/warmup?grip_type_id=half_crimp")
        )

        // Session setup (/session/new) is NOT restorable
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/new"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/new/"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/new?exercise=hangboard"))

        // POST endpoints / intermediate actions are NOT restorable
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/create"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/workset"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/set"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/set/delete"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/set/restore"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/workset/delete"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/estimate"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/check"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/update"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/session/pain-report"))

        // Other non-session pages are NOT restorable
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/dashboard"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/climbs"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/profile"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/history"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/login"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath("/register"))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath(null))
        assertFalse(SessionLifecycleHelper.isRestorableSessionPath(""))
    }

    @Test
    fun testIsRecentlySaved() {
        val now = 100_000_000L
        val threeHoursMs = 3 * 3600 * 1000L

        // Just saved
        assertTrue(SessionLifecycleHelper.isRecentlySaved(now, now))
        // 1 hour ago
        assertTrue(SessionLifecycleHelper.isRecentlySaved(now - 3600 * 1000L, now))
        // 2 hours 59 minutes ago
        assertTrue(SessionLifecycleHelper.isRecentlySaved(now - (threeHoursMs - 1), now))

        // Exactly 3 hours ago or older -> expired
        assertFalse(SessionLifecycleHelper.isRecentlySaved(now - threeHoursMs, now))
        assertFalse(SessionLifecycleHelper.isRecentlySaved(now - (threeHoursMs + 1000), now))
        assertFalse(SessionLifecycleHelper.isRecentlySaved(now - 24 * 3600 * 1000L, now))

        // Invalid / zero / future timestamps
        assertFalse(SessionLifecycleHelper.isRecentlySaved(0L, now))
        assertFalse(SessionLifecycleHelper.isRecentlySaved(-1L, now))
        assertFalse(SessionLifecycleHelper.isRecentlySaved(now + 1000L, now))
    }

    @Test
    fun testTabRootsAndHomePage() {
        assertTrue(SessionLifecycleHelper.isHomePage("http://127.0.0.1:8000/"))
        assertTrue(SessionLifecycleHelper.isHomePage("http://127.0.0.1:8000"))
        assertTrue(SessionLifecycleHelper.isHomePage("/"))
        assertFalse(SessionLifecycleHelper.isHomePage("http://127.0.0.1:8000/dashboard"))
        assertFalse(SessionLifecycleHelper.isHomePage("http://127.0.0.1:8000/session/new"))

        // Tab roots
        assertTrue(SessionLifecycleHelper.isTabRoot("http://127.0.0.1:8000/"))
        assertTrue(SessionLifecycleHelper.isTabRoot("http://127.0.0.1:8000/dashboard"))
        assertTrue(SessionLifecycleHelper.isTabRoot("http://127.0.0.1:8000/climbs"))
        assertTrue(SessionLifecycleHelper.isTabRoot("http://127.0.0.1:8000/profile"))
        assertTrue(SessionLifecycleHelper.isTabRoot("http://127.0.0.1:8000/session/new"))

        // Non tab roots (sub-pages or flow pages)
        assertFalse(SessionLifecycleHelper.isTabRoot("http://127.0.0.1:8000/session/worksets"))
        assertFalse(SessionLifecycleHelper.isTabRoot("http://127.0.0.1:8000/session/warmup"))
        assertFalse(SessionLifecycleHelper.isTabRoot("http://127.0.0.1:8000/login"))
        assertFalse(SessionLifecycleHelper.isTabRoot("http://127.0.0.1:8000/register"))
        assertFalse(SessionLifecycleHelper.isTabRoot("http://127.0.0.1:8000/plates"))
        assertFalse(SessionLifecycleHelper.isTabRoot("http://127.0.0.1:8000/history"))
    }
}
