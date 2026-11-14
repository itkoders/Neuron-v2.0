package uz.itkoders.neyron.sms

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

object Api {
    fun post(path: String, body: JSONObject, token: String? = null): JSONObject =
        request("POST", path, body, token)

    fun get(path: String, token: String): JSONObject =
        request("GET", path, null, token)

    private fun request(method: String, path: String, body: JSONObject?, token: String?): JSONObject {
        val connection = (URL(BuildConfig.API_BASE_URL.trimEnd('/') + path).openConnection() as HttpURLConnection)
        connection.requestMethod = method
        connection.connectTimeout = 15000
        connection.readTimeout = 20000
        connection.setRequestProperty("Accept", "application/json")
        if (token != null) connection.setRequestProperty("Authorization", "Bearer $token")
        if (body != null) {
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
        }
        return try {
            val stream = if (connection.responseCode in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: "{}"
            JSONObject(text)
        } finally {
            connection.disconnect()
        }
    }
}
