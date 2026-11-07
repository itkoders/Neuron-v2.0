package uz.itkoders.neuron

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.rgb(12, 18, 38)
        window.navigationBarColor = Color.rgb(12, 18, 38)
        showFoundationScreen()
    }

    private fun showFoundationScreen() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(28, 36, 28, 36)
            setBackgroundColor(Color.rgb(12, 18, 38))
        }

        val brand = TextView(this).apply {
            text = "NEURON"
            textSize = 34f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            letterSpacing = 0.16f
        }
        val subtitle = TextView(this).apply {
            text = "SMART JOURNAL"
            textSize = 13f
            setTextColor(Color.rgb(132, 160, 255))
            gravity = Gravity.CENTER
            letterSpacing = 0.22f
        }
        val title = TextView(this).apply {
            text = "Ta’lim boshqaruvi — yagona ilovada"
            textSize = 21f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            setPadding(0, 42, 0, 12)
        }
        val body = TextView(this).apply {
            text = "Android ilovasining xavfsiz asosiy qismi yaratildi. O‘qituvchi, o‘quvchi va ota-ona kabinetlari mavjud NEURON serveriga ulanadi. Telegram botning alohida jarayoni bu ilovada ishga tushirilmaydi."
            textSize = 15f
            setTextColor(Color.rgb(194, 202, 222))
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, 28)
        }
        val status = TextView(this).apply {
            text = "1-bosqich: Android APK tuzilmasi"
            textSize = 13f
            setTextColor(Color.rgb(112, 225, 184))
            gravity = Gravity.CENTER
        }

        root.addView(brand, matchWrap())
        root.addView(subtitle, matchWrap())
        root.addView(title, matchWrap())
        root.addView(body, matchWrap())
        root.addView(status, matchWrap())
        setContentView(root)
    }

    private fun matchWrap() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT
    )
}
