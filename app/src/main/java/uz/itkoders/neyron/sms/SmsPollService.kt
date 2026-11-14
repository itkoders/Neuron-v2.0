package uz.itkoders.neyron.sms

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.IBinder
import android.telephony.SmsManager
import androidx.core.app.NotificationCompat
import org.json.JSONObject

class SmsPollService : Service() {
    @Volatile private var running = false
    private var worker: Thread? = null
    private val prefs by lazy { getSharedPreferences("neyron_sms_private", MODE_PRIVATE) }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "STOP") {
            stopSelf()
            return START_NOT_STICKY
        }
        if (checkSelfPermission(android.Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
            stopSelf()
            return START_NOT_STICKY
        }
        createChannel()
        startForeground(42, buildNotification())
        if (!running) {
            running = true
            worker = Thread { pollLoop() }.also { it.start() }
        }
        return START_STICKY
    }

    private fun pollLoop() {
        while (running) {
            try {
                val token = prefs.getString("device_token", null)
                if (token.isNullOrBlank()) {
                    running = false
                    stopSelf()
                    break
                }
                val response = Api.get("/api/sms/tasks", token)
                if (response.optBoolean("ok")) {
                    val tasks = response.optJSONArray("tasks")
                    if (tasks != null) {
                        for (i in 0 until tasks.length()) {
                            val task = tasks.getJSONObject(i)
                            processTask(token, task)
                        }
                    }
                } else if (response.optString("error") == "device_auth") {
                    running = false
                    stopSelf()
                    break
                }
            } catch (_: Exception) {
                // Internet vaqtincha uzilsa, keyingi aylanishda qayta urinadi.
            }
            try { Thread.sleep(20_000) } catch (_: InterruptedException) { break }
        }
    }

    private fun processTask(token: String, task: JSONObject) {
        val id = task.optString("id")
        val phone = task.optString("phone")
        val body = task.optString("body")
        try {
            val manager = smsManager()
            val parts = manager.divideMessage(body)
            if (parts.size > 1) manager.sendMultipartTextMessage(phone, null, parts, null, null)
            else manager.sendTextMessage(phone, null, body, null, null)
            Api.post("/api/sms/tasks/$id/report", JSONObject().put("status", "sent"), token)
        } catch (e: Exception) {
            try {
                Api.post("/api/sms/tasks/$id/report",
                    JSONObject().put("status", "failed").put("error", e.message ?: "SMS yuborilmadi"), token)
            } catch (_: Exception) { }
        }
    }

    @Suppress("DEPRECATION")
    private fun smsManager(): SmsManager {
        return if (Build.VERSION.SDK_INT >= 31) getSystemService(SmsManager::class.java)
        else SmsManager.getDefault()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            val channel = NotificationChannel("neyron_sms", "NEYRON SMS xizmati", NotificationManager.IMPORTANCE_LOW)
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, "neyron_sms")
            .setSmallIcon(android.R.drawable.ic_dialog_email)
            .setContentTitle("NEYRON SMS faol")
            .setContentText("Yangi ball xabarlari tekshirilmoqda")
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    override fun onDestroy() {
        running = false
        worker?.interrupt()
        super.onDestroy()
    }
}
