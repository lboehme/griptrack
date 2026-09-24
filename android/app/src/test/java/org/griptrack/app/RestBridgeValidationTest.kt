package org.griptrack.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Input validation for the S3 native rest bridge (#148, docs/adr/0015):
 * page script can call window.GripTrackNative, so rest ends and text are
 * bounded before anything is posted or scheduled.
 */
class RestBridgeValidationTest {

    private val now = 1_800_000_000_000L

    @Test
    fun restEndMustBeInTheFutureAndAtMostThirtyMinutesAhead() {
        assertFalse(RestBridge.isValidRestEnd(now - 1, now))
        assertFalse(RestBridge.isValidRestEnd(now, now))
        assertTrue(RestBridge.isValidRestEnd(now + 1, now))
        assertTrue(RestBridge.isValidRestEnd(now + 30 * 60 * 1000L, now))
        assertFalse(RestBridge.isValidRestEnd(now + 30 * 60 * 1000L + 1, now))
    }

    @Test
    fun textIsCappedAndStrippedOfControlCharacters() {
        assertEquals("", RestBridge.cleanText(null))
        assertEquals("Rest · set 2 of 3 next", RestBridge.cleanText("Rest · set 2 of 3 next"))
        assertEquals("ab", RestBridge.cleanText("a\nb"))
        assertEquals(RestBridge.MAX_TEXT_LENGTH, RestBridge.cleanText("x".repeat(500)).length)
    }
}
