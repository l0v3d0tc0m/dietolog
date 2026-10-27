package dev.healthagent.sync

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

/** One screen: server address, token, permissions button, sync button, last status. */
class MainActivity : ComponentActivity() {
    private lateinit var prefs: Prefs
    private lateinit var status: TextView

    private val requestPermissions =
        registerForActivityResult(PermissionController.createRequestPermissionResultContract()) { granted ->
            val missing = HealthSync.ALL_PERMISSIONS - granted
            status.text = if (missing.isEmpty()) "Все разрешения выданы"
            else "Не выдано: ${missing.joinToString { it.substringAfterLast('.') }}"
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)

        val pad = (16 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 3, pad, pad)
        }
        val url = EditText(this).apply {
            hint = "http://192.168.1.10:8765"
            setText(prefs.serverUrl)
            inputType = InputType.TYPE_TEXT_VARIATION_URI
        }
        val token = EditText(this).apply {
            hint = "INGEST_TOKEN из .env"
            setText(prefs.token)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        status = TextView(this).apply { text = prefs.lastStatus; setPadding(0, pad, 0, 0) }

        val permButton = Button(this).apply {
            text = "Разрешения Health Connect"
            setOnClickListener { askPermissions() }
        }
        val syncButton = Button(this).apply {
            text = "Синхронизировать сейчас"
            setOnClickListener {
                prefs.serverUrl = HealthSync.normalizeUrl(url.text.toString())
                url.setText(prefs.serverUrl)
                prefs.token = token.text.toString().trim()
                SyncWorker.schedule(this@MainActivity)
                syncNow()
            }
        }

        root.addView(TextView(this).apply { text = "Адрес сервера на ПК" })
        root.addView(url)
        root.addView(TextView(this).apply { text = "Токен" })
        root.addView(token)
        root.addView(permButton)
        root.addView(syncButton)
        root.addView(status)

        // Android 15+ draws apps under the status bar; push the content below it and the nav bar
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            v.setPadding(pad, pad + bars.top, pad, pad + bars.bottom)
            insets
        }
        setContentView(ScrollView(this).apply { addView(root) })

        SyncWorker.schedule(this)
    }

    private fun askPermissions() {
        when (HealthConnectClient.getSdkStatus(this)) {
            HealthConnectClient.SDK_AVAILABLE -> requestPermissions.launch(HealthSync.ALL_PERMISSIONS)
            HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> startActivity(
                Intent(Intent.ACTION_VIEW, Uri.parse(
                    "market://details?id=com.google.android.apps.healthdata&url=healthconnect%3A%2F%2Fonboarding"))
            )
            else -> status.text = "Health Connect недоступен на этом телефоне"
        }
    }

    private fun syncNow() {
        status.text = "Синхронизирую…"
        lifecycleScope.launch {
            val result = try {
                HealthSync.run(this@MainActivity)
            } catch (e: Exception) {
                "ошибка: ${e.message}"
            }
            prefs.lastStatus = "${now()} вручную: $result"
            status.text = prefs.lastStatus
        }
    }
}
