package org.griptrack.app

import android.annotation.SuppressLint
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.util.Log
import android.view.View
import android.webkit.CookieManager
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Main Activity embedding the GripTrack WebView shell (#98, #99, PRD #93).
 *
 * Bootstraps the embedded Python FastAPI backend on a background thread,
 * polls /health behind a splash screen, and loads the WebView at the exact
 * 127.0.0.1:<port> bound by the server once healthy. Supports file downloads
 * (export archives) and file uploads (restore archive).
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "GripTrackActivity"
    }

    private lateinit var webView: WebView
    private lateinit var splashContainer: View
    private lateinit var progressBar: ProgressBar
    private lateinit var statusText: TextView
    private lateinit var errorContainer: View
    private lateinit var errorDetailText: TextView
    private lateinit var retryButton: Button

    private var hasLoadedInitialUrl = false
    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null

    private val fileChooserLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        val uri = if (result.resultCode == RESULT_OK) result.data?.data else null
        fileChooserCallback?.onReceiveValue(if (uri != null) arrayOf(uri) else null)
        fileChooserCallback = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        initViews()
        setupWebView()
        setupBackNavigation()

        retryButton.setOnClickListener {
            startServer()
        }

        startServer()
    }

    private fun initViews() {
        webView = findViewById(R.id.webView)
        splashContainer = findViewById(R.id.splashContainer)
        progressBar = findViewById(R.id.progressBar)
        statusText = findViewById(R.id.statusText)
        errorContainer = findViewById(R.id.errorContainer)
        errorDetailText = findViewById(R.id.errorDetailText)
        retryButton = findViewById(R.id.retryButton)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            cacheMode = WebSettings.LOAD_DEFAULT
            loadsImagesAutomatically = true
        }

        CookieManager.getInstance().setAcceptCookie(true)

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val url = request?.url?.toString() ?: return false
                // Keep loopback navigations within the WebView
                return if (url.startsWith(ServerManager.serverUrl)) {
                    false
                } else {
                    // Let external links open in standard browser if needed
                    super.shouldOverrideUrlLoading(view, request)
                }
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                CookieManager.getInstance().flush()
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                fileChooserCallback?.onReceiveValue(null)
                fileChooserCallback = filePathCallback

                val intent = fileChooserParams?.createIntent() ?: Intent(Intent.ACTION_GET_CONTENT).apply {
                    type = "*/*"
                    addCategory(Intent.CATEGORY_OPENABLE)
                }
                return try {
                    fileChooserLauncher.launch(intent)
                    true
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to launch file chooser", e)
                    fileChooserCallback?.onReceiveValue(null)
                    fileChooserCallback = null
                    false
                }
            }
        }

        webView.setDownloadListener { url, userAgent, contentDisposition, mimetype, _ ->
            downloadFromLoopback(url, contentDisposition, mimetype)
        }
    }

    private fun downloadFromLoopback(url: String, contentDisposition: String?, mimetype: String?) {
        Thread({
            try {
                val filename = URLUtil.guessFileName(url, contentDisposition, mimetype).let {
                    if (it.endsWith(".bin") && url.contains("export")) "griptrack-export.zip" else it
                }
                val cookies = CookieManager.getInstance().getCookie(url)

                val conn = (URL(url).openConnection() as HttpURLConnection).apply {
                    connectTimeout = 5000
                    readTimeout = 10000
                    if (!cookies.isNullOrEmpty()) {
                        setRequestProperty("Cookie", cookies)
                    }
                }

                if (conn.responseCode in 200..299) {
                    val bytes = conn.inputStream.use { it.readBytes() }
                    conn.disconnect()

                    val saved = saveToDownloads(filename, mimetype ?: "application/zip", bytes)
                    Handler(Looper.getMainLooper()).post {
                        if (saved) {
                            Toast.makeText(this, "Saved $filename to Downloads", Toast.LENGTH_LONG).show()
                        } else {
                            Toast.makeText(this, "Failed to save export to Downloads", Toast.LENGTH_SHORT).show()
                        }
                    }
                } else {
                    Log.e(TAG, "Download failed with HTTP ${conn.responseCode}")
                    conn.disconnect()
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error downloading from loopback", e)
            }
        }, "GripTrack-DownloadWorker").start()
    }

    private fun saveToDownloads(filename: String, mimeType: String, data: ByteArray): Boolean {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val contentValues = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, filename)
                    put(MediaStore.Downloads.MIME_TYPE, mimeType)
                    put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                }
                val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)
                    ?: return false
                contentResolver.openOutputStream(uri)?.use { out ->
                    out.write(data)
                }
                true
            } else {
                val dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                dir.mkdirs()
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

    private fun setupBackNavigation() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (::webView.isInitialized && webView.visibility == View.VISIBLE && webView.canGoBack()) {
                    webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })
    }

    private fun startServer() {
        showLoadingState()

        ServerManager.start(
            context = this,
            onReady = ::onServerReady,
            onError = ::onServerError
        )
    }

    private fun showLoadingState() {
        progressBar.visibility = View.VISIBLE
        statusText.visibility = View.VISIBLE
        statusText.setText(R.string.starting_server)
        errorContainer.visibility = View.GONE
        splashContainer.visibility = View.VISIBLE
    }

    private fun onServerReady(url: String) {
        Log.i(TAG, "Server ready, loading WebView at: $url")
        if (!hasLoadedInitialUrl) {
            webView.loadUrl(url)
            hasLoadedInitialUrl = true
        }
        splashContainer.visibility = View.GONE
        webView.visibility = View.VISIBLE
    }

    private fun onServerError(error: Throwable) {
        Log.e(TAG, "Server error: ${error.message}", error)
        progressBar.visibility = View.GONE
        statusText.visibility = View.GONE
        errorContainer.visibility = View.VISIBLE
        errorDetailText.text = error.stackTraceToString()
    }

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
    }

    override fun onDestroy() {
        super.onDestroy()
        if (isFinishing) {
            webView.destroy()
        }
    }
}
