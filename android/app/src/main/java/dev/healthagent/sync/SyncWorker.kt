package dev.healthagent.sync

import android.content.Context
import android.content.SharedPreferences
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.io.IOException
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        return try {
            prefs.lastStatus = "${now()} фон: ${HealthSync.run(applicationContext)}"
            Result.success()
        } catch (e: IOException) {
            prefs.lastStatus = "${now()} фон: сервер недоступен (${e.message})"
            Result.retry()
        } catch (e: Exception) {
            prefs.lastStatus = "${now()} фон: ошибка ${e.message}"
            Result.failure()
        }
    }

    companion object {
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<SyncWorker>(30, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork("health-sync", ExistingPeriodicWorkPolicy.KEEP, request)
        }
    }
}

fun now(): String = LocalDateTime.now().format(DateTimeFormatter.ofPattern("dd.MM HH:mm"))

class Prefs(context: Context) {
    private val p: SharedPreferences = context.getSharedPreferences("sync", Context.MODE_PRIVATE)
    var serverUrl: String
        get() = p.getString("url", "") ?: ""
        set(v) = p.edit().putString("url", v).apply()
    var token: String
        get() = p.getString("token", "") ?: ""
        set(v) = p.edit().putString("token", v).apply()
    var lastStatus: String
        get() = p.getString("status", "ещё не синхронизировалось") ?: ""
        set(v) = p.edit().putString("status", v).apply()
}
