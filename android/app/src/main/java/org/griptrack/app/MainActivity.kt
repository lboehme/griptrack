package org.griptrack.app

import android.annotation.SuppressLint
import android.content.Context
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
 * Main Activity embedding the GripTrack WebView shell (#98, #99, PRD #93, #139, #140).
 *
 * Bootstraps the embedded Python FastAPI backend on a background thread,
 * polls /health behind a splash screen, and loads the WebView at the exact
 * 127.0.0.1:<port> bound by the server once healthy. Supports file downloads
 * (export archives) and file uploads (restore archive).
 *
 * Preserves mid-session state across Activity recreation and process death (#140, §2.3)
 * and conforms Back button navigation to Android app conventions (#140, §2.4).
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
    private var savedStateBundle: Bundle? = null
    private var currentRelativeUrl: String? = null
    private var lastUrlSavedTimestamp: Long = 0L
    private var previousLoadedUrl: String? = null
    private var clearHistoryOnNextPageFinished = false
    private var isNavigatingHome = false
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
        savedStateBundle = savedInstanceState

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

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        updateSystemBarAppearance(newConfig)
    }

    private fun updateSystemBarAppearance(config: Configuration = resources.configuration) {
        val insetsController = WindowInsetsControllerCompat(window, window.decorView)
        val isDarkMode = (config.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
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

        val errorInitialLeft = errorContainer.paddingLeft
        val errorInitialTop = errorContainer.paddingTop
        val errorInitialRight = errorContainer.paddingRight
        val errorInitialBottom = errorContainer.paddingBottom

        ViewCompat.setOnApplyWindowInsetsListener(errorContainer) { view, windowInsets ->
            val insets = windowInsets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime()
            )
            view.updatePadding(
                left = errorInitialLeft + insets.left,
                top = errorInitialTop + insets.top,
                right = errorInitialRight + insets.right,
                bottom = errorInitialBottom + insets.bottom
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
                return if (SessionLifecycleHelper.isLoopbackUrl(url)) {
                    false
                } else {
                    // Let external links open in standard browser if needed
                    super.shouldOverrideUrlLoading(view, request)
                }
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                CookieManager.getInstance().flush()

                isNavigatingHome = false

                if (clearHistoryOnNextPageFinished) {
                    clearHistoryOnNextPageFinished = false
                    view?.clearHistory()
                }

                val currentPath = SessionLifecycleHelper.normalizePath(url)
                val previousPath = SessionLifecycleHelper.normalizePath(previousLoadedUrl)
                val wasAuth = previousPath == "/login" || previousPath == "/register"
                val isAuth = currentPath == "/login" || currentPath == "/register"

                // Once signed in / navigated away from auth pages, clear history so Back never returns to auth
                if (wasAuth && !isAuth) {
                    view?.clearHistory()
                }
                previousLoadedUrl = url

                // Save path and timestamp for same-origin URLs across recreation and process death
                val relativeUrl = SessionLifecycleHelper.extractPathAndQuery(url)
                if (relativeUrl != null) {
                    val now = System.currentTimeMillis()
                    currentRelativeUrl = relativeUrl
                    lastUrlSavedTimestamp = now
                    getSharedPreferences(SessionLifecycleHelper.PREFS_NAME, Context.MODE_PRIVATE)
                        .edit()
                        .putString(SessionLifecycleHelper.KEY_SAVED_PATH, relativeUrl)
                        .putLong(SessionLifecycleHelper.KEY_SAVED_TIME, now)
                        .apply()
                }
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
                if (!::webView.isInitialized || webView.visibility != View.VISIBLE) {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                    return
                }

                if (isNavigatingHome) {
                    // Ignore additional back presses while navigating home to prevent premature exit
                    return
                }

                val currentUrl = webView.url
                val currentPath = SessionLifecycleHelper.normalizePath(currentUrl)

                // 1. If current page is home (/), exit activity
                if (currentPath == SessionLifecycleHelper.HOME_PATH) {
                    finish()
                    return
                }

                // 2. If current page is a tab root other than /, navigate to / and clear history
                if (SessionLifecycleHelper.TAB_ROOTS.contains(currentPath)) {
                    navigateToHomeAndClearHistory()
                    return
                }

                // 3. Everywhere else: step back through history, skipping auth pages (/login, /register)
                val history = webView.copyBackForwardList()
                val currentIndex = history.currentIndex
                var step = -1
                while (currentIndex + step >= 0) {
                    val item = history.getItemAtIndex(currentIndex + step)
                    val itemPath = SessionLifecycleHelper.normalizePath(item.url)
                    if (itemPath != "/login" && itemPath != "/register") {
                        break
                    }
                    step--
                }

                if (currentIndex + step >= 0) {
                    webView.goBackOrForward(step)
                } else {
                    // No valid non-auth history to step back into; return to home
                    navigateToHomeAndClearHistory()
                }
            }
        })
    }

    private fun navigateToHomeAndClearHistory() {
        isNavigatingHome = true
        clearHistoryOnNextPageFinished = true
        webView.loadUrl("${ServerManager.serverUrl}/")
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
            loadInitialPage(url)
            hasLoadedInitialUrl = true
        }
        errorContainer.visibility = View.GONE
        webView.visibility = View.VISIBLE
        ViewCompat.requestApplyInsets(webView)
    }

    private fun loadInitialPage(serverUrl: String) {
        val prefs = getSharedPreferences(SessionLifecycleHelper.PREFS_NAME, Context.MODE_PRIVATE)
        val savedPath = savedStateBundle?.getString(SessionLifecycleHelper.KEY_SAVED_PATH)
            ?: prefs.getString(SessionLifecycleHelper.KEY_SAVED_PATH, null)
        val savedTime = savedStateBundle?.getLong(SessionLifecycleHelper.KEY_SAVED_TIME, 0L)?.takeIf { it > 0L }
            ?: prefs.getLong(SessionLifecycleHelper.KEY_SAVED_TIME, 0L)

        val shouldRestoreSession = SessionLifecycleHelper.isRestorableSessionPath(savedPath) &&
            SessionLifecycleHelper.isRecentlySaved(savedTime)

        if (shouldRestoreSession && savedPath != null) {
            Log.i(TAG, "Restoring active session from $savedPath (saved at $savedTime)")
            var restored = false
            val bundle = savedStateBundle
            if (bundle != null) {
                // Full Activity-recreation restore (rotation, etc.): the
                // WebView's own cookie jar and DOM state come back as-is,
                // so there's no cold start here and no need to re-run
                // device sign-in.
                restored = (webView.restoreState(bundle) != null)
            }
            if (!restored) {
                val path = if (savedPath.startsWith("/")) savedPath else "/$savedPath"
                deviceSignIn(serverUrl, next = path)
            }
        } else {
            Log.i(TAG, "Loading root URL (savedPath=$savedPath, savedTime=$savedTime, shouldRestore=$shouldRestoreSession)")
            clearHistoryOnNextPageFinished = true
            deviceSignIn(serverUrl, next = null)
        }
        savedStateBundle = null
    }

    /**
     * Cold-start sign-in (#145, ADR-0013): exchange the device token the
     * launcher provisioned in app-private storage for a session cookie by
     * POSTing to /device-login, landing on `next` (a same-origin relative
     * path the server validates) or Home on success. Doing this exchange
     * on every cold start is simpler than tracking whether the existing
     * cookie is still valid, and is cheap (one local loopback POST).
     *
     * Falls back to a plain load of `next`/`/` if the token file can't be
     * read yet -- the server will then just render its own
     * anonymous/first-run response, same as before this device-login flow
     * existed.
     */
    private fun deviceSignIn(serverUrl: String, next: String?) {
        val token = ServerManager.deviceToken(this)
        if (token == null) {
            Log.w(TAG, "No device token available; loading ${next ?: "/"} directly")
            webView.loadUrl("$serverUrl${next ?: "/"}")
            return
        }
        val formBody = StringBuilder("token=").append(Uri.encode(token))
        if (next != null) {
            formBody.append("&next=").append(Uri.encode(next))
        }
        webView.postUrl("$serverUrl/device-login", formBody.toString().toByteArray(Charsets.UTF_8))
    }

    private fun onServerError(error: Throwable) {
        Log.e(TAG, "Server error: ${error.message}", error)
        webView.visibility = View.GONE
        errorContainer.visibility = View.VISIBLE
        errorDetailText.text = error.stackTraceToString()
        ViewCompat.requestApplyInsets(errorContainer)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (::webView.isInitialized) {
            webView.saveState(outState)
        }
        val prefs = getSharedPreferences(SessionLifecycleHelper.PREFS_NAME, Context.MODE_PRIVATE)
        val path = currentRelativeUrl ?: prefs.getString(SessionLifecycleHelper.KEY_SAVED_PATH, null)
        val time = if (lastUrlSavedTimestamp > 0L) lastUrlSavedTimestamp else prefs.getLong(SessionLifecycleHelper.KEY_SAVED_TIME, 0L)
        if (path != null) {
            outState.putString(SessionLifecycleHelper.KEY_SAVED_PATH, path)
            outState.putLong(SessionLifecycleHelper.KEY_SAVED_TIME, time)
        }
    }

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
    }

    override fun onDestroy() {
        super.onDestroy()
        if (isFinishing && ::webView.isInitialized) {
            webView.destroy()
        }
    }
}
