package org.griptrack.app

import android.annotation.SuppressLint
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.view.View
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.updatePadding

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
        val splashScreen = installSplashScreen()
        super.onCreate(savedInstanceState)

        splashScreen.setKeepOnScreenCondition {
            ServerManager.state != ServerManager.State.RUNNING && ServerManager.state != ServerManager.State.ERROR
        }

        WindowCompat.setDecorFitsSystemWindows(window, false)

        if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.VANILLA_ICE_CREAM) {
            @Suppress("DEPRECATION")
            window.statusBarColor = Color.TRANSPARENT
            @Suppress("DEPRECATION")
            window.navigationBarColor = Color.TRANSPARENT
        }

        updateSystemBarAppearance()

        setContentView(R.layout.activity_main)

        initViews()
        setupEdgeToEdgeInsets()
        setupWebView()
        setupBackNavigation()

        retryButton.setOnClickListener {
            startServer()
        }

        startServer()
    }

    override fun onResume() {
        super.onResume()
        updateSystemBarAppearance()
    }

    private fun updateSystemBarAppearance() {
        val insetsController = WindowInsetsControllerCompat(window, window.decorView)
        val isDarkMode = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        insetsController.isAppearanceLightStatusBars = !isDarkMode
        insetsController.isAppearanceLightNavigationBars = !isDarkMode
    }

    private fun initViews() {
        webView = findViewById(R.id.webView)
        errorContainer = findViewById(R.id.errorContainer)
        errorDetailText = findViewById(R.id.errorDetailText)
        retryButton = findViewById(R.id.retryButton)
    }

    private fun setupEdgeToEdgeInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(webView) { view, windowInsets ->
            val insets = windowInsets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime()
            )
            view.updatePadding(
                left = insets.left,
                top = insets.top,
                right = insets.right,
                bottom = insets.bottom
            )
            windowInsets
        }

        ViewCompat.setOnApplyWindowInsetsListener(errorContainer) { view, windowInsets ->
            val insets = windowInsets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime()
            )
            view.updatePadding(
                left = insets.left,
                top = insets.top,
                right = insets.right,
                bottom = insets.bottom
            )
            windowInsets
        }
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

        webView.setDownloadListener { url, _, contentDisposition, mimetype, _ ->
            DownloadHelper.download(this, url, contentDisposition, mimetype)
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
        errorContainer.visibility = View.GONE

        ServerManager.start(
            context = this,
            onReady = ::onServerReady,
            onError = ::onServerError
        )
    }

    private fun onServerReady(url: String) {
        Log.i(TAG, "Server ready, loading WebView at: $url")
        if (!hasLoadedInitialUrl) {
            webView.loadUrl(url)
            hasLoadedInitialUrl = true
        }
        errorContainer.visibility = View.GONE
        webView.visibility = View.VISIBLE
        ViewCompat.requestApplyInsets(webView)
    }

    private fun onServerError(error: Throwable) {
        Log.e(TAG, "Server error: ${error.message}", error)
        webView.visibility = View.GONE
        errorContainer.visibility = View.VISIBLE
        errorDetailText.text = error.stackTraceToString()
        ViewCompat.requestApplyInsets(errorContainer)
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
