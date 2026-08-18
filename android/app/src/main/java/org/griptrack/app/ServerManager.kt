package org.griptrack.app

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.chaquo.python.PyException
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Manages the embedded Python FastAPI backend lifecycle.
 *
 * Runs as a long-lived singleton across the Android process lifecycle (PRD #93)
 * so Activity recreation or backgrounding does not restart the server or lose state.
 */
object ServerManager {

    private const val TAG = "GripTrackServer"
    const val LOOPBACK_HOST = "127.0.0.1"
    const val DEFAULT_PORT = 8000
    private const val HEALTH_TIMEOUT_MS = 45_000L
    private const val HEALTH_POLL_INTERVAL_MS = 200L

    val serverUrl: String
        get() = "http://$LOOPBACK_HOST:$DEFAULT_PORT"

    enum class State {
        STOPPED,
        STARTING,
        RUNNING,
        ERROR
    }

    @Volatile
    var state: State = State.STOPPED
        private set

    @Volatile
    var lastError: Throwable? = null
        private set

    private var serverThread: Thread? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private val isPolling = AtomicBoolean(false)

    private val readyCallbacks = CopyOnWriteArrayList<(url: String) -> Unit>()
    private val errorCallbacks = CopyOnWriteArrayList<(error: Throwable) -> Unit>()

    @Synchronized
    fun start(
        context: Context,
        onReady: (url: String) -> Unit,
        onError: (error: Throwable) -> Unit
    ) {
        when (state) {
            State.RUNNING -> {
                mainHandler.post { onReady(serverUrl) }
                return
            }
            State.STARTING -> {
                readyCallbacks.add(onReady)
                errorCallbacks.add(onError)
                return
            }
            State.STOPPED, State.ERROR -> {
                state = State.STARTING
                lastError = null
                readyCallbacks.add(onReady)
                errorCallbacks.add(onError)
            }
        }

        val appContext = context.applicationContext

        serverThread = Thread({
            try {
                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(appContext))
                }
                val py = Python.getInstance()
                val launcher = py.getModule("backend.launcher")

                val appDir = appContext.filesDir.absolutePath
                Log.i(TAG, "Starting embedded server with app_dir=$appDir on $LOOPBACK_HOST:$DEFAULT_PORT")

                launcher.callAttr("serve", appDir, LOOPBACK_HOST, DEFAULT_PORT)
                Log.i(TAG, "Server run() exited normally")
            } catch (e: PyException) {
                Log.e(TAG, "Python exception in embedded server: ${e.message}", e)
                notifyError(e)
            } catch (t: Throwable) {
                Log.e(TAG, "Unexpected error in server thread: ${t.message}", t)
                notifyError(t)
            }
        }, "GripTrack-EmbeddedServer").apply {
            isDaemon = true
            start()
        }

        startHealthPolling()
    }

    private fun startHealthPolling() {
        if (isPolling.getAndSet(true)) return

        val healthThread = Thread({
            val startTime = System.currentTimeMillis()
            val healthUrl = URL("$serverUrl/health")
            var healthy = false

            while (System.currentTimeMillis() - startTime < HEALTH_TIMEOUT_MS) {
                if (state == State.ERROR) {
                    isPolling.set(false)
                    return@Thread
                }
                try {
                    val conn = (healthUrl.openConnection() as HttpURLConnection).apply {
                        connectTimeout = 1000
                        readTimeout = 1000
                        instanceFollowRedirects = false
                        requestMethod = "GET"
                    }
                    val code = conn.responseCode
                    conn.disconnect()
                    if (code == 200) {
                        healthy = true
                        break
                    }
                } catch (_: Exception) {
                    // Server not ready yet; wait and retry
                }

                try {
                    Thread.sleep(HEALTH_POLL_INTERVAL_MS)
                } catch (_: InterruptedException) {
                    break
                }
            }

            isPolling.set(false)

            if (healthy) {
                state = State.RUNNING
                Log.i(TAG, "Server health check succeeded. Server is RUNNING at $serverUrl")
                mainHandler.post {
                    val callbacks = ArrayList(readyCallbacks)
                    readyCallbacks.clear()
                    errorCallbacks.clear()
                    callbacks.forEach { it(serverUrl) }
                }
            } else if (state != State.ERROR) {
                val timeoutError = IllegalStateException(
                    "Embedded server failed to respond on /health within ${HEALTH_TIMEOUT_MS / 1000}s"
                )
                notifyError(timeoutError)
            }
        }, "GripTrack-HealthPoller")

        healthThread.isDaemon = true
        healthThread.start()
    }

    private fun notifyError(error: Throwable) {
        state = State.ERROR
        lastError = error
        isPolling.set(false)
        mainHandler.post {
            val callbacks = ArrayList(errorCallbacks)
            readyCallbacks.clear()
            errorCallbacks.clear()
            callbacks.forEach { it(error) }
        }
    }
}
