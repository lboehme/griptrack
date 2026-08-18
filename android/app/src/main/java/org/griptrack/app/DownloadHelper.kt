package org.griptrack.app

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.util.Log
import android.webkit.CookieManager
import android.webkit.URLUtil
import android.widget.Toast
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.regex.Pattern

/**
 * Handles loopback file downloads (e.g. data export archives) and persists
 * them to the public Downloads collection (#99).
 */
object DownloadHelper {

    private const val TAG = "GripTrackDownload"
    private val FILENAME_REGEX = Pattern.compile("""filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?""", Pattern.CASE_INSENSITIVE)

    fun download(
        context: Context,
        url: String,
        contentDisposition: String?,
        mimeType: String?
    ) {
        val appContext = context.applicationContext
        Thread({
            try {
                val resolvedFilename = extractFilename(url, contentDisposition, mimeType)
                val resolvedMime = mimeType?.takeIf { it.isNotBlank() } ?: "application/zip"
                val cookies = CookieManager.getInstance().getCookie(url)

                val conn = (URL(url).openConnection() as HttpURLConnection).apply {
                    connectTimeout = 5000
                    readTimeout = 10000
                    if (!cookies.isNullOrEmpty()) {
                        setRequestProperty("Cookie", cookies)
                    }
                }

                val responseCode = conn.responseCode
                if (responseCode in 200..299) {
                    val bytes = conn.inputStream.use { it.readBytes() }
                    conn.disconnect()

                    val saved = saveToDownloads(appContext, resolvedFilename, resolvedMime, bytes)
                    Handler(Looper.getMainLooper()).post {
                        if (saved) {
                            Toast.makeText(appContext, "Saved $resolvedFilename to Downloads", Toast.LENGTH_LONG).show()
                        } else {
                            Toast.makeText(appContext, "Failed to save download to storage", Toast.LENGTH_SHORT).show()
                        }
                    }
                } else {
                    Log.e(TAG, "Download failed with HTTP $responseCode")
                    conn.disconnect()
                    Handler(Looper.getMainLooper()).post {
                        Toast.makeText(appContext, "Download failed (HTTP $responseCode)", Toast.LENGTH_SHORT).show()
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error downloading from $url", e)
                Handler(Looper.getMainLooper()).post {
                    Toast.makeText(appContext, "Download error: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }, "GripTrack-DownloadWorker").start()
    }

    private fun extractFilename(url: String, contentDisposition: String?, mimeType: String?): String {
        if (!contentDisposition.isNullOrBlank()) {
            val matcher = FILENAME_REGEX.matcher(contentDisposition)
            if (matcher.find()) {
                val match = matcher.group(1)
                if (!match.isNullOrBlank()) {
                    return match.trim()
                }
            }
        }
        val guessed = URLUtil.guessFileName(url, contentDisposition, mimeType)
        return if (guessed.endsWith(".bin") || guessed.isBlank()) {
            "griptrack-export.zip"
        } else {
            guessed
        }
    }

    private fun saveToDownloads(
        context: Context,
        filename: String,
        mimeType: String,
        data: ByteArray
    ): Boolean {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val contentValues = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, filename)
                    put(MediaStore.Downloads.MIME_TYPE, mimeType)
                    put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                }
                val uri: Uri? = context.contentResolver.insert(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    contentValues
                )
                if (uri != null) {
                    context.contentResolver.openOutputStream(uri)?.use { out ->
                        out.write(data)
                    }
                    true
                } else {
                    false
                }
            } else {
                val dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                if (!dir.exists()) {
                    dir.mkdirs()
                }
                val file = File(dir, filename)
                FileOutputStream(file).use { out ->
                    out.write(data)
                }
                true
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save file to downloads", e)
            false
        }
    }
}
