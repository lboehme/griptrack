package org.griptrack.app

import android.app.Notification
import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import android.os.VibrationAttributes
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log

/**
 * Fires at the rest end scheduled by [RestBridge.startRest] (#148,
 * docs/adr/0015): vibrates a short pattern, plays the default notification
 * sound when the user's Rest sound setting is on, and flips the rest
 * notification to the rest-over line ("Pull. Set N is ready"). Declared
 * `exported=false` in the manifest -- only this app's own alarm reaches it.
 *
 * The vibration is issued directly with alarm usage (not through the
 * notification), so it still happens with the screen off, with the app in
 * the background, and when notifications are denied.
 */
class RestAlarmReceiver : BroadcastReceiver() {

    companion object {
        private const val TAG = "GripTrackRest"
        private val VIBRATION_PATTERN = longArrayOf(0L, 400L, 200L, 400L, 200L, 600L)
    }

    override fun onReceive(context: Context, intent: Intent) {
        vibrate(context)
        if (intent.getBooleanExtra(RestBridge.EXTRA_SOUND, false)) {
            playSound(context)
        }
        postReady(
            context,
            RestBridge.cleanText(intent.getStringExtra(RestBridge.EXTRA_READY)).ifEmpty { "Pull. Rest is over" },
            RestBridge.cleanText(intent.getStringExtra(RestBridge.EXTRA_DETAIL))
        )
    }

    private fun vibrate(context: Context) {
        val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            context.getSystemService(VibratorManager::class.java)?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Vibrator::class.java)
        }
        if (vibrator == null || !vibrator.hasVibrator()) return
        val effect = VibrationEffect.createWaveform(VIBRATION_PATTERN, -1)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                vibrator.vibrate(effect, VibrationAttributes.createForUsage(VibrationAttributes.USAGE_ALARM))
            } else {
                val audioAttributes = AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
                @Suppress("DEPRECATION")
                vibrator.vibrate(effect, audioAttributes)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Rest-over vibration failed", e)
        }
    }

    private fun playSound(context: Context) {
        try {
            val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION) ?: return
            val ringtone = RingtoneManager.getRingtone(context, uri) ?: return
            ringtone.audioAttributes = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build()
            ringtone.play()
        } catch (e: Exception) {
            Log.w(TAG, "Rest-over sound failed", e)
        }
    }

    private fun postReady(context: Context, title: String, detail: String) {
        if (!RestBridge.canNotify(context)) return
        RestBridge.ensureChannel(context)
        val notification = Notification.Builder(context, RestBridge.CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(detail)
            .setShowWhen(true)
            .setOnlyAlertOnce(true)
            .setAutoCancel(true)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setContentIntent(RestBridge.contentIntent(context))
            .build()
        try {
            context.getSystemService(NotificationManager::class.java)?.notify(RestBridge.NOTIFICATION_ID, notification)
        } catch (e: SecurityException) {
            Log.w(TAG, "Notification permission revoked; rest-over vibrated only", e)
        }
    }
}
