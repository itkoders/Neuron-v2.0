package uz.itkoders.neuron

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Build
import android.view.Gravity
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import android.webkit.ValueCallback
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private val executor = Executors.newSingleThreadExecutor()
    private lateinit var tokenStore: SecureTokenStore
    private lateinit var root: LinearLayout
    private lateinit var codeInput: EditText
    private lateinit var status: TextView
    private lateinit var progress: ProgressBar
    private var webView: WebView? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private val filePickerRequest = 7104

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        tokenStore = SecureTokenStore(this)
        val saved = tokenStore.read()
        if (saved != null) openMiniApp() else showLogin()
    }

    private fun showLogin() {
        webView?.destroy()
        webView = null

        // ScrollView keeps the login screen usable with large system fonts
        // and on short displays; controls use content-driven heights.
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(24), dp(28), dp(24), dp(28))
            setBackgroundColor(Color.rgb(8, 15, 30))
        }
        val scroll = android.widget.ScrollView(this).apply {
            isFillViewport = true
            clipToPadding = false
            setBackgroundColor(Color.rgb(8, 15, 30))
            addView(content, android.widget.ScrollView.LayoutParams(-1, -1))
        }

        val title = TextView(this).apply {
            text = "NEURON"
            textSize = 34f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            includeFontPadding = true
        }
        val subtitle = TextView(this).apply {
            text = "Ta’lim boshqaruv tizimi"
            textSize = 16f
            setTextColor(Color.LTGRAY)
            gravity = Gravity.CENTER
            includeFontPadding = true
        }
        codeInput = EditText(this).apply {
            hint = "Telegram botdan olingan 10 xonali kod"
            setSingleLine(true)
            textSize = 16f
            setTextColor(Color.WHITE)
            setHintTextColor(Color.rgb(165, 178, 198))
            inputType = android.text.InputType.TYPE_CLASS_NUMBER
            filters = arrayOf(android.text.InputFilter.LengthFilter(10))
            gravity = Gravity.CENTER_VERTICAL
            includeFontPadding = true
            minHeight = dp(68)
            setPadding(dp(18), dp(12), dp(18), dp(12))
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(Color.rgb(17, 29, 49))
                cornerRadius = dp(14).toFloat()
                setStroke(dp(1), Color.rgb(58, 75, 100))
            }
        }
        val button = Button(this).apply {
            text = "Xavfsiz kirish"
            isAllCaps = false
            textSize = 16f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            minHeight = dp(60)
            setPadding(dp(16), dp(12), dp(16), dp(12))
            backgroundTintList = null
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(Color.rgb(13, 148, 136))
                cornerRadius = dp(14).toFloat()
            }
            setOnClickListener { exchangeCode() }
        }
        status = TextView(this).apply {
            text = "Telegram botda /apk buyrug‘ini yuboring. Kod 5 daqiqa amal qiladi."
            textSize = 14f
            setTextColor(Color.LTGRAY)
            gravity = Gravity.CENTER
            includeFontPadding = true
            setPadding(dp(4), dp(4), dp(4), dp(4))
        }
        progress = ProgressBar(this).apply { visibility = View.GONE }

        content.addView(title, matchWrap())
        content.addView(subtitle, matchWrap())
        content.addView(codeInput, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(32) })
        content.addView(button, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(14) })
        content.addView(progress, matchWrap())
        content.addView(status, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(18) })
        setContentView(scroll)
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density + 0.5f).toInt()

    private fun matchWrap() = LinearLayout.LayoutParams(-1, -2)

    private fun exchangeCode() {
        val code = codeInput.text.toString().trim()
        if (!code.matches(Regex("\\d{10}"))) {
            status.text = "10 xonali kodni to‘liq kiriting."
            return
        }
        val base = BuildConfig.NEURON_BASE_URL.trimEnd('/')
        if (!base.startsWith("https://") || base.contains("example.invalid")) {
            status.text = "Server manzili sozlanmagan. Administratorga murojaat qiling."
            return
        }
        progress.visibility = View.VISIBLE
        status.text = "Kod tekshirilmoqda…"
        executor.execute {
            var connection: HttpURLConnection? = null
            try {
                connection = (URL("$base/api/android/login").openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = 15000
                    readTimeout = 20000
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                    setRequestProperty("Accept", "application/json")
                }
                connection.outputStream.use {
                    it.write(JSONObject().put("code", code).toString().toByteArray(Charsets.UTF_8))
                }
                val statusCode = connection.responseCode
                val stream = if (statusCode in 200..299) connection.inputStream else connection.errorStream
                val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
                if (statusCode !in 200..299) {
                    val message = try {
                        JSONObject(response).optString("error", "Kod noto‘g‘ri yoki muddati tugagan.")
                    } catch (_: Exception) { "Kirish amalga oshmadi. Yangi kod oling." }
                    runOnUiThread { progress.visibility = View.GONE; status.text = message }
                    return@execute
                }
                val token = JSONObject(response).optString("session_token")
                if (token.length !in 40..512) throw IllegalStateException("Invalid session")
                tokenStore.save(token)
                runOnUiThread { openMiniApp() }
            } catch (_: Exception) {
                runOnUiThread {
                    progress.visibility = View.GONE
                    status.text = "Serverga ulanib bo‘lmadi. Internetni tekshiring."
                }
            } finally {
                connection?.disconnect()
            }
        }
    }

    private inner class SessionBridge {
        @JavascriptInterface
        fun getSessionToken(): String = tokenStore.read().orEmpty()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun openMiniApp() {
        val base = BuildConfig.NEURON_BASE_URL.trimEnd('/')
        val baseUri = Uri.parse(base)
        val page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.rgb(8, 15, 30))
        }
        val top = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(12, 4, 12, 4)
        }
        val brand = TextView(this).apply {
            text = "NEURON"
            textSize = 16f
            setTextColor(Color.WHITE)
            setPadding(8, 8, 8, 8)
        }
        val logout = Button(this).apply {
            text = "Chiqish"
            setOnClickListener {
                val oldToken = tokenStore.read()
                executor.execute {
                    try {
                        if (!oldToken.isNullOrBlank()) {
                            val connection = (URL(BuildConfig.NEURON_BASE_URL.trimEnd('/') + "/api/android/logout").openConnection() as HttpURLConnection)
                            connection.requestMethod = "POST"
                            connection.connectTimeout = 5000
                            connection.readTimeout = 5000
                            connection.setRequestProperty("Authorization", "Bearer " + oldToken)
                            connection.setRequestProperty("Content-Type", "application/json")
                            connection.doOutput = true
                            connection.outputStream.use { it.write("{}".toByteArray(Charsets.UTF_8)) }
                            connection.responseCode
                            connection.disconnect()
                        }
                    } catch (_: Exception) {
                        // Local logout still proceeds when the device is offline.
                    }
                    runOnUiThread {
                        tokenStore.clear()
                        showLogin()
                    }
                }
            }
        }
        top.addView(brand, LinearLayout.LayoutParams(0, -2, 1f))
        top.addView(logout, LinearLayout.LayoutParams(-2, -2))
        val browser = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.javaScriptCanOpenWindowsAutomatically = false
            settings.setSupportMultipleWindows(false)
            settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
            if (Build.VERSION.SDK_INT >= 26) settings.safeBrowsingEnabled = true
            addJavascriptInterface(SessionBridge(), "NeuronAndroid")
            webChromeClient = object : WebChromeClient() {
                override fun onShowFileChooser(
                    view: WebView?,
                    callback: ValueCallback<Array<Uri>>?,
                    params: FileChooserParams?
                ): Boolean {
                    fileCallback?.onReceiveValue(null)
                    fileCallback = callback
                    val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = "*/*"
                    }
                    return try {
                        startActivityForResult(Intent.createChooser(intent, "Faylni tanlang"), filePickerRequest)
                        true
                    } catch (_: Exception) {
                        fileCallback = null
                        false
                    }
                }
            }
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val uri = request.url
                    val uriPort = if (uri.port == -1) 443 else uri.port
                    val basePort = if (baseUri.port == -1) 443 else baseUri.port
                    val sameOrigin = uri.scheme == "https" &&
                        uri.host.equals(baseUri.host, ignoreCase = true) &&
                        uriPort == basePort
                    if (sameOrigin) return false
                    if (uri.scheme == "https" || uri.scheme == "tel" || uri.scheme == "mailto") {
                        try { startActivity(Intent(Intent.ACTION_VIEW, uri)) } catch (_: Exception) {}
                    }
                    return true
                }
            }
            loadUrl("$base/app?platform=android&role=entry")
        }
        webView = browser
        page.addView(top, LinearLayout.LayoutParams(-1, -2))
        page.addView(browser, LinearLayout.LayoutParams(-1, 0, 1f))
        setContentView(page)
    }

    @Deprecated("Deprecated in Android")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == filePickerRequest) {
            val result = if (resultCode == RESULT_OK && data?.data != null) arrayOf(data.data!!) else null
            fileCallback?.onReceiveValue(result)
            fileCallback = null
        }
    }

    @Deprecated("Deprecated in Android")
    override fun onBackPressed() {
        val browser = webView
        if (browser != null && browser.canGoBack()) browser.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        fileCallback?.onReceiveValue(null)
        webView?.destroy()
        executor.shutdown()
        super.onDestroy()
    }
}
