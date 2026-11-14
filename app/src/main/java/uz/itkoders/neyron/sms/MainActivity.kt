package uz.itkoders.neyron.sms

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import org.json.JSONObject

class MainActivity : Activity() {
    private lateinit var codeInput: EditText
    private lateinit var statusText: TextView
    private val prefs by lazy { getSharedPreferences("neyron_sms_private", MODE_PRIVATE) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildScreen()
        statusText.text = if (prefs.getString("device_token", null) == null)
            "Holat: telefon hali ulanmagan"
        else "Holat: telefon ulangan. SMS xizmatini yoqishingiz mumkin."
    }

    private fun buildScreen() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(24, 32, 24, 24)
        }
        val title = TextView(this).apply {
            text = "NEYRON SMS"
            textSize = 28f
            setTextColor(0xFF172554.toInt())
            gravity = Gravity.CENTER
        }
        val intro = TextView(this).apply {
            text = "O‘qituvchining o‘z SIM-kartasi orqali ota-onalarga ball xabarlari yuboriladi."
            textSize = 16f
            setPadding(0, 18, 0, 18)
        }
        codeInput = EditText(this).apply {
            hint = "Mini ilovadan olingan 6 xonali ulash kodi"
            inputType = 2
            setSingleLine(true)
        }
        val pairButton = Button(this).apply {
            text = "TELEFONNI ULASH"
            setOnClickListener { pairPhone() }
        }
        val startButton = Button(this).apply {
            text = "SMS XIZMATINI YOQISH"
            setOnClickListener { startSmsService() }
        }
        val stopButton = Button(this).apply {
            text = "VAQTINCHA TO‘XTATISH"
            setOnClickListener {
                stopService(Intent(this@MainActivity, SmsPollService::class.java))
                statusText.text = "Holat: xizmat vaqtincha to‘xtatildi."
            }
        }
        statusText = TextView(this).apply {
            textSize = 15f
            setPadding(0, 18, 0, 18)
        }
        val warning = TextView(this).apply {
            text = "Muhim: SMS o‘qituvchining SIM-kartasidan va operator balansidan yuboriladi. Internet, SMS ruxsati va xizmat bildirishnomasi kerak. Ikki SIM bo‘lsa, standart SMS SIM-kartasini tekshiring. Android 15/16 da ushbu fon xizmati 6 soatlik tizim chekloviga ega; to‘xtasa, ilovani qayta ochib xizmatni yana yoqing."
            textSize = 13f
            setTextColor(0xFF7C2D12.toInt())
            setPadding(0, 16, 0, 0)
        }
        listOf(title, intro, codeInput, pairButton, startButton, stopButton, statusText, warning).forEach {
            root.addView(it, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = 10 })
        }
        setContentView(root)
    }

    private fun pairPhone() {
        val code = codeInput.text.toString().trim()
        if (code.length != 6 || !code.all { it.isDigit() }) {
            Toast.makeText(this, "6 xonali kodni kiriting", Toast.LENGTH_SHORT).show()
            return
        }
        statusText.text = "Telefon ulanmoqda..."
        Thread {
            try {
                val body = JSONObject()
                    .put("code", code)
                    .put("device_name", Build.MANUFACTURER + " " + Build.MODEL)
                val result = Api.post("/api/sms/device/pair", body)
                val token = result.optString("device_token")
                if (!result.optBoolean("ok") || token.isBlank()) throw Exception("Kod noto‘g‘ri yoki muddati tugagan")
                prefs.edit().putString("device_token", token).apply()
                runOnUiThread {
                    codeInput.text.clear()
                    statusText.text = "Telefon muvaffaqiyatli ulandi. Endi SMS xizmatini yoqing."
                    Toast.makeText(this, "NEYRON bilan ulanish tayyor", Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                runOnUiThread { statusText.text = "Ulanmadi: ${e.message ?: "internetni tekshiring"}" }
            }
        }.start()
    }

    private fun startSmsService() {
        if (prefs.getString("device_token", null).isNullOrBlank()) {
            Toast.makeText(this, "Avval telefonni ulash kodi bilan ulang", Toast.LENGTH_LONG).show()
            return
        }
        if (checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.SEND_SMS), 210)
            return
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 211)
            return
        }
        val intent = Intent(this, SmsPollService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
        statusText.text = "Holat: SMS xizmati ishga tushdi."
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if ((requestCode == 210 || requestCode == 211) &&
            grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
            startSmsService()
        } else if (requestCode == 210) {
            statusText.text = "SMS ruxsati berilmadi. Avtomatik SMS yuborib bo‘lmaydi."
        }
    }
}
