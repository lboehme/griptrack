package org.griptrack.app

import android.Manifest
import android.app.Activity
import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import android.view.WindowManager
import android.webkit.JavascriptInterface

/**
 * The S3 native rest bridge (#148, docs/adr/0015), registered on the WebView
 * as `window.GripTrackNative`. Exactly three things, and nothing more:
 *
 * 1. [setKeepScreenOn] toggles the window's FLAG_KEEP_SCREEN_ON while
 *    `/session/play` is showing.
 * 2. [startRest] posts (or updates) a lock-screen notification counting down
 *    to the rest end with the system chronometer -- no foreground service,
 *    no action buttons -- and schedules an exact alarm for that end.
 * 3. [stopRest] cancels both.
 *
 * The alarm fires [RestAlarmReceiver], which vibrates (plus a sound when the
 * user's Rest sound setting is on) and flips the notification to the
 * rest-over line. The web countdown stays the source of truth for what the
 * app shows; the alarm is the source of truth for the alert.
 *
 * `@JavascriptInterface` methods run on a WebView background thread, so
 * anything touching the window or requesting a permission hops to the UI
 * thread. Every call is ignored unless the page currently loaded is the
 * loopback server ([pageIsTrusted], maintained by MainActivity), and all
 * inputs are validated/capped, since this is callable from page script.
 */
class RestBridge(private val activity: Activity) {

    companion object {
        private const val TAG = "GripTrackRest"
        const val JS_NAME = "GripTrackNative"

        const val CHANNEL_ID = "rest_timer"
        const val NOTIFICATION_ID = 148
        private const val ALARM_REQUEST_CODE = 148
        private const val CONTENT_REQUEST_CODE = 149

        const val EXTRA_TITLE = "org.griptrack.app.extra.REST_TITLE"
        const val EXTRA_DETAIL = "org.griptrack.app.extra.REST_DETAIL"
        const val EXTRA_READY = "org.griptrack.app.extra.REST_READY"
        const val EXTRA_SOUND = "org.griptrack.app.extra.REST_SOUND"

        const val MAX_TEXT_LENGTH = 80
        const val MAX_REST_AHEAD_MS = 30 * 60 * 1000L

        private const val KEY_ASKED_NOTIFICATIONS = "asked_notification_permission"
        private const val NOTIFICATION_PERMISSION_REQUEST_CODE = 1480

        /** Caps page-supplied text: at most [MAX_TEXT_LENGTH] chars, no control characters. */
        fun cleanText(value: String?): String {
            if (value == null) return ""
            return value.filter { !it.isISOControl() }.take(MAX_TEXT_LENGTH)
        }

        /** Whether a rest end is plausible: in the future, at most 30 minutes ahead. */
        fun isValidRestEnd(endsAtEpochMs: Long, nowMs: Long = System.currentTimeMillis()): Boolean {
            return endsAtEpochMs > nowMs && endsAtEpochMs <= nowMs + MAX_REST_AHEAD_MS
        }

        /** Creates the "Rest timer" channel (idempotent). Silent on post: the alarm does the alerting. */
        fun ensureChannel(context: Context) {
            val manager = context.getSystemService(NotificationManager::class.java) ?: return
            if (manager.getNotificationChannel(CHANNEL_ID) != null) return
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Rest timer",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                description = "Rest countdown on the lock screen and the rest-over alert"
                setSound(null, null)
                enableVibration(false)
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            }
            manager.createNotificationChannel(channel)
        }

        /** Whether this app may post notifications right now. */
        fun canNotify(context: Context): Boolean {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
            ) {
                return false
            }
            val manager = context.getSystemService(NotificationManager::class.java) ?: return false
            return manager.areNotificationsEnabled()
        }

        /** Tapping the notification behaves like the launcher icon: it resumes the task, or cold-starts
         * MainActivity, whose saved-URL restore (#140) lands back on /session/play. */
        fun contentIntent(context: Context): PendingIntent {
            val intent = Intent(context, MainActivity::class.java).apply {
                action = Intent.ACTION_MAIN
                addCategory(Intent.CATEGORY_LAUNCHER)
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED
            }
            return PendingIntent.getActivity(
                context,
                CONTENT_REQUEST_CODE,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        }

        fun alarmIntent(context: Context, title: String, detail: String, ready: String, sound: Boolean): PendingIntent {
            val intent = Intent(context, RestAlarmReceiver::class.java).apply {
                putExtra(EXTRA_TITLE, title)
                putExtra(EXTRA_DETAIL, detail)
                putExtra(EXTRA_READY, ready)
                putExtra(EXTRA_SOUND, sound)
            }
            return PendingIntent.getBroadcast(
                context,
                ALARM_REQUEST_CODE,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        }
    }

    private val appContext: Context = activity.applicationContext

    /** Set by MainActivity on every page start: true only for the loopback server's own pages. */
    @Volatile
    var pageIsTrusted: Boolean = false

    @JavascriptInterface
    fun setKeepScreenOn(on: Boolean) {
        if (!pageIsTrusted) return
        activity.runOnUiThread {
            if (on) {
                activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            } else {
                activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }
    }

    @JavascriptInterface
    fun startRest(endsAtEpochMs: Long, title: String?, detail: String?, sound: Boolean, readyTitle: String?) {
        if (!pageIsTrusted) return
        if (!isValidRestEnd(endsAtEpochMs)) {
            Log.w(TAG, "Ignoring startRest with out-of-range end $endsAtEpochMs")
            return
        }
        val cleanTitle = cleanText(title).ifEmpty { "Rest" }
        val cleanDetail = cleanText(detail)
        val cleanReady = cleanText(readyTitle).ifEmpty { "Pull. Rest is over" }

        requestNotificationPermissionOnce()
        ensureChannel(appContext)
        postCountdown(endsAtEpochMs, cleanTitle, cleanDetail)
        scheduleAlarm(endsAtEpochMs, alarmIntent(appContext, cleanTitle, cleanDetail, cleanReady, sound))
    }

    @JavascriptInterface
    fun stopRest() {
        if (!pageIsTrusted) return
        val alarmManager = appContext.getSystemService(AlarmManager::class.java)
        alarmManager?.cancel(alarmIntent(appContext, "", "", "", false))
        appContext.getSystemService(NotificationManager::class.java)?.cancel(NOTIFICATION_ID)
    }

    private fun postCountdown(endsAtEpochMs: Long, title: String, detail: String) {
        if (!canNotify(appContext)) return
        val notification = Notification.Builder(appContext, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(detail)
            .setWhen(endsAtEpochMs)
            .setShowWhen(true)
            .setUsesChronometer(true)
            .setChronometerCountDown(true)
            .setOnlyAlertOnce(true)
            .setOngoing(true)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setContentIntent(contentIntent(appContext))
            .build()
        try {
            appContext.getSystemService(NotificationManager::class.java)?.notify(NOTIFICATION_ID, notification)
        } catch (e: SecurityException) {
            Log.w(TAG, "Notification permission revoked; skipping rest countdown", e)
        }
    }

    private fun scheduleAlarm(endsAtEpochMs: Long, pendingIntent: PendingIntent) {
        val alarmManager = appContext.getSystemService(AlarmManager::class.java) ?: return
        val exactAllowed = Build.VERSION.SDK_INT < Build.VERSION_CODES.S || alarmManager.canScheduleExactAlarms()
        try {
            if (exactAllowed) {
                alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, endsAtEpochMs, pendingIntent)
            } else {
                // Fallback: inexact, may land a little late, but still fires with the screen off.
                alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, endsAtEpochMs, pendingIntent)
            }
        } catch (e: SecurityException) {
            Log.w(TAG, "Exact alarm refused; falling back to an inexact alarm", e)
            alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, endsAtEpochMs, pendingIntent)
        }
    }

    /** Android 13+: ask for the notification permission once, the first time a rest starts.
     * Denied means no countdown notification -- the alarm's vibration still happens. */
    private fun requestNotificationPermissionOnce() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (appContext.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
        val prefs = appContext.getSharedPreferences(SessionLifecycleHelper.PREFS_NAME, Context.MODE_PRIVATE)
        if (prefs.getBoolean(KEY_ASKED_NOTIFICATIONS, false)) return
        prefs.edit().putBoolean(KEY_ASKED_NOTIFICATIONS, true).apply()
        activity.runOnUiThread {
            activity.requestPermissions(
                arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                NOTIFICATION_PERMISSION_REQUEST_CODE
            )
        }
    }
}
