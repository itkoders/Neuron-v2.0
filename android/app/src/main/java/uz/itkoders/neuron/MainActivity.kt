package uz.itkoders.neuron

import android.app.Activity
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient

class MainActivity : Activity() {
    private lateinit var web: WebView
    private val apiUrl = BuildConfig.NEURON_API_URL.trimEnd('/')

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.rgb(12, 18, 38)
        window.navigationBarColor = Color.rgb(12, 18, 38)
        web = WebView(this).apply {
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.javaScriptCanOpenWindowsAutomatically = false
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val uri = request.url
                    if (uri.scheme == "neuron" && uri.host == "auth") {
                        val code = uri.getQueryParameter("code") ?: return true
                        view.loadUrl("$apiUrl/mobile?code=${Uri.encode(code)}")
                        return true
                    }
                    return uri.scheme != "https" && uri.scheme != "http"
                }
            }
        }
        setContentView(web)
        handleAuthIntent(intent)
        if (intent?.data == null) web.loadUrl("$apiUrl/mobile")
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleAuthIntent(intent)
    }

    private fun handleAuthIntent(source: android.content.Intent?) {
        val uri = source?.data ?: return
        if (uri.scheme == "neuron" && uri.host == "auth") {
            val code = uri.getQueryParameter("code") ?: return
            web.loadUrl("$apiUrl/mobile?code=${Uri.encode(code)}")
        }
    }

    @Deprecated("Deprecated in Android API")
    override fun onBackPressed() {
        if (::web.isInitialized && web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}
