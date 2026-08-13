package org.griptrack.app

import android.os.Bundle
import android.util.Log
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.PyException
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * Feasibility probe for issue #97 (GripTrack Android pivot, PRD #93).
 *
 * On launch, starts the embedded CPython 3.12 runtime (Chaquopy) and runs
 * two checks defined in `app/src/main/python/feasibility_check.py`:
 *   1. `import bcrypt` + a real hashpw/checkpw round-trip (the Rust
 *      `_bcrypt` extension — what `backend.auth` uses for every login).
 *   2. `import pydantic_core` + a SchemaValidator round-trip (the Rust
 *      core every Pydantic/SQLModel model relies on for every request).
 *
 * Results are shown on screen AND logged to Logcat (tag
 * "GripTrackFeasibility") so they're readable via `adb logcat -s
 * GripTrackFeasibility` without needing to look at the phone screen. This
 * IS the acceptance-criteria probe for #97 — see
 * docs/android-feasibility.md for exactly how to read the result and the
 * go/no-go criteria it feeds.
 *
 * Deliberately does nothing else: no WebView, no embedded server, no
 * backend import. That's #98's scope.
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "GripTrackFeasibility"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val resultView = findViewById<TextView>(R.id.resultText)

        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        val module = Python.getInstance().getModule("feasibility_check")

        val lines = mutableListOf<String>()

        // Both checks always run, independent of each other's outcome — a
        // FAIL on one shouldn't hide whether the other also fails.
        val bcryptPassed = runCheck(module, "check_bcrypt", "bcrypt", lines)
        val pydanticCorePassed = runCheck(module, "check_pydantic_core", "pydantic_core", lines)
        val allPassed = bcryptPassed && pydanticCorePassed

        lines.add("")
        lines.add(
            if (allPassed) {
                "GO — both checks passed. See docs/android-feasibility.md to record the outcome on #97."
            } else {
                "NO-GO — at least one check failed. See docs/android-feasibility.md before proceeding to #98."
            }
        )

        val report = lines.joinToString("\n")
        resultView.text = report
        Log.i(TAG, report)
    }

    /**
     * Runs one Python-side check function (no-arg, returns a detail string
     * on success, raises on failure) and appends a PASS/FAIL line.
     *
     * Returns whether the check passed.
     */
    private fun runCheck(
        module: PyObject,
        function: String,
        label: String,
        lines: MutableList<String>,
    ): Boolean {
        return try {
            val detail = module.callAttr(function).toString()
            val line = "PASS  $label: $detail"
            lines.add(line)
            Log.i(TAG, line)
            true
        } catch (e: PyException) {
            val line = "FAIL  $label: ${e.message}"
            lines.add(line)
            Log.e(TAG, line, e)
            false
        }
    }
}
