package org.griptrack.app

import android.annotation.SuppressLint
import android.os.Bundle
import android.util.Log
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity

/**
 * Main Activity embedding the GripTrack WebView shell (#98, PRD #93).
 *
 * Bootstraps the embedded Python FastAPI backend on a background thread,
 * polls /health behind a splash screen, and loads the WebView at the exact
 * 127.0.0.1:<port> bound by the server once healthy.
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
