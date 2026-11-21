package uz.itkoders.neuron

import android.annotation.SuppressLint
import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private val executor = Executors.newSingleThreadExecutor()
    private lateinit var root: LinearLayout
    private lateinit var codeInput: EditText
    private lateinit var status: TextView
    private lateinit var progress: ProgressBar
    private var webView: WebView? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        showLogin()
    }

    private fun showLogin() {
        root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(32, 36, 32, 36)
            setBackgroundColor(Color.rgb(8, 15, 30))
        }
        val title = TextView(this).apply {
            text = "NEURON"
            textSize = 32f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
        }
        val subtitle = TextView(this).apply {
            text = "Ta’lim boshqaruv tizimi"
            textSize = 15f
            setTextColor(Color.LTGRAY)
            gravity = Gravity.CENTER
        }
        codeInput = EditText(this).apply {
            hint = "Telegram botdan olingan kod"
            setSingleLine(true)
            textSize = 17f
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
            inputType = android.text.InputType.TYPE_CLASS_NUMBER
        }
        val button = Button(this).apply {
            text = "Kirish"
            setOnClickListener { exchangeCode() }
        }
        status = TextView(this).apply {
            text = "Kirish kodi Telegram bot orqali olinadi."
            setTextColor(Color.LTGRAY)
            gravity = Gravity.CENTER
        }
        progress = ProgressBar(this).apply { visibility = View.GONE }
        root.addView(title, matchWrap())
        root.addView(subtitle, matchWrap())
        root.addView(codeInput, LinearLayout.LayoutParams(-1, 58).apply { topMargin = 28 })
        root.addView(button, LinearLayout.LayoutParams(-1, 52).apply { topMargin = 12 })
        root.addView(progress, matchWrap())
        root.addView(status, LinearLayout.LayoutParams(-1, -2).apply { topMargin = 16 })
        setContentView(root)
    }

    private fun matchWrap() = LinearLayout.LayoutParams(-1, -2)

    private fun exchangeCode() {
        val code = codeInput.text.toString().trim()
        if (code.isBlank()) {
            status.text = "Kirish kodini kiriting."
            return
        }
        val base = BuildConfig.NEURON_BASE_URL.trimEnd('/')
        if (!base.startsWith("https://") || base.contains("example.invalid")) {
            status.text = "Ilova server manzili sozlanmagan. Administratorga murojaat qiling."
            return
        }
        progress.visibility = View.VISIBLE
        status.text = "Kod tekshirilmoqda…"
        executor.execute {
            try {
                val connection = (URL("$base/api/android/login").openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = 15000
                    readTimeout = 20000
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                }
                connection.outputStream.use {
                    it.write(JSONObject().put("code", code).toString().toByteArray(Charsets.UTF_8))
                }
                val stream = if (connection.responseCode in 200..299) connection.inputStream else connection.errorStream
                val response = stream.bufferedReader().use { it.readText() }
                if (connection.responseCode !in 200..299) {
                    val message = try { JSONObject(response).optString("error", "Kod noto‘g‘ri yoki muddati tugagan.") } catch (_: Exception) { "Kirish amalga oshmadi." }
                    runOnUiThread { progress.visibility = View.GONE; status.text = message }
                    return@execute
                }
                val token = JSONObject(response).optString("session_token")
                if (token.isBlank()) throw IllegalStateException("Server sessiya tokenini qaytarmadi.")
                runOnUiThread { openMiniApp(token) }
                connection.disconnect()
            } catch (e: Exception) {
                runOnUiThread {
                    progress.visibility = View.GONE
                    status.text = "Ulanishda xato. Internetni va serverni tekshiring."
                }
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun openMiniApp(token: String) {
        val base = BuildConfig.NEURON_BASE_URL.trimEnd('/')
        val browser = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView, url: String) {
                    if (url.startsWith(base)) {
                        val safeToken = JSONObject.quote(token)
                        view.evaluateJavascript("localStorage.setItem('neuron_android_token', $safeToken);", null)
                    }
                }
            }
            loadUrl("$base/app?platform=android")
        }
        webView = browser
        setContentView(browser)
    }

    @Deprecated("Deprecated in Android")
    override fun onBackPressed() {
        val browser = webView
        if (browser != null && browser.canGoBack()) browser.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        webView?.destroy()
        executor.shutdown()
        super.onDestroy()
    }
}
