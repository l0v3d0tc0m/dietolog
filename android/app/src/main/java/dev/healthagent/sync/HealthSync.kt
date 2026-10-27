package dev.healthagent.sync

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.aggregate.AggregateMetric
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.MealType
import androidx.health.connect.client.records.NutritionRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.request.AggregateGroupByPeriodRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.Period
import java.time.ZoneId
import kotlin.reflect.KClass

/** Reads the last DAYS days from Health Connect and posts them to the PC. */
object HealthSync {
    private const val DAYS = 7L
    const val BACKGROUND_PERMISSION = "android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND"

    val DATA_PERMISSIONS: Set<String> = setOf(
        StepsRecord::class, DistanceRecord::class, ActiveCaloriesBurnedRecord::class,
        TotalCaloriesBurnedRecord::class, HeartRateRecord::class, RestingHeartRateRecord::class,
        SleepSessionRecord::class, NutritionRecord::class, WeightRecord::class,
    ).map { HealthPermission.getReadPermission(it) }.toSet()

    val ALL_PERMISSIONS = DATA_PERMISSIONS + BACKGROUND_PERMISSION

    private fun perm(type: KClass<out Record>) = HealthPermission.getReadPermission(type)

    /** "192.168.1.105:8765/" -> "http://192.168.1.105:8765" */
    fun normalizeUrl(raw: String): String {
        val trimmed = raw.trim().trimEnd('/')
        return if (trimmed.contains("://")) trimmed else "http://$trimmed"
    }

    suspend fun run(context: Context): String {
        val prefs = Prefs(context)
        require(prefs.serverUrl.isNotBlank() && prefs.token.isNotBlank()) { "Укажи адрес сервера и токен" }
        val url = normalizeUrl(prefs.serverUrl)

        val client = HealthConnectClient.getOrCreate(context)
        val granted = client.permissionController.getGrantedPermissions()
        if (granted.intersect(DATA_PERMISSIONS).isEmpty()) {
            throw SecurityException("Нет разрешений Health Connect")
        }

        val zone = ZoneId.systemDefault()
        val today = LocalDate.now(zone)
        val from = today.minusDays(DAYS - 1)
        val start = from.atStartOfDay(zone).toInstant()
        val end = Instant.now()

        val payload = JSONObject()
            .put("range_from", from.toString())
            .put("range_to", today.toString())
            .put("days", readDays(client, granted, from, today))

        if (perm(SleepSessionRecord::class) in granted) {
            // Look back a bit further so last night's sleep that started before midnight is included
            payload.put("sleep", readSleep(client, start.minus(Duration.ofHours(12)), end))
        }
        if (perm(NutritionRecord::class) in granted) {
            payload.put("food", readFood(client, start, end))
        }
        if (perm(WeightRecord::class) in granted) {
            payload.put("weight", readWeight(client, start, end))
        }

        val response = post("$url/ingest", prefs.token, payload.toString())
        return "OK: $response"
    }

    private suspend fun readDays(
        client: HealthConnectClient, granted: Set<String>, from: LocalDate, today: LocalDate,
    ): JSONArray {
        // Aggregation fails if any metric's permission is missing, so ask only for granted ones
        val metrics = buildSet<AggregateMetric<*>> {
            if (perm(StepsRecord::class) in granted) add(StepsRecord.COUNT_TOTAL)
            if (perm(DistanceRecord::class) in granted) add(DistanceRecord.DISTANCE_TOTAL)
            if (perm(ActiveCaloriesBurnedRecord::class) in granted) add(ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL)
            if (perm(TotalCaloriesBurnedRecord::class) in granted) add(TotalCaloriesBurnedRecord.ENERGY_TOTAL)
            if (perm(HeartRateRecord::class) in granted) add(HeartRateRecord.BPM_AVG)
            if (perm(RestingHeartRateRecord::class) in granted) add(RestingHeartRateRecord.BPM_AVG)
        }
        val out = JSONArray()
        if (metrics.isEmpty()) return out

        val groups = client.aggregateGroupByPeriod(
            AggregateGroupByPeriodRequest(
                metrics = metrics,
                timeRangeFilter = TimeRangeFilter.between(
                    from.atStartOfDay(), today.plusDays(1).atStartOfDay(),
                ),
                timeRangeSlicer = Period.ofDays(1),
            )
        )
        for (g in groups) {
            val r = g.result
            out.put(JSONObject()
                .put("date", g.startTime.toLocalDate().toString())
                .putOpt("steps", r[StepsRecord.COUNT_TOTAL])
                .putOpt("distance_m", r[DistanceRecord.DISTANCE_TOTAL]?.inMeters)
                .putOpt("active_kcal", r[ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL]?.inKilocalories)
                .putOpt("total_kcal", r[TotalCaloriesBurnedRecord.ENERGY_TOTAL]?.inKilocalories)
                .putOpt("avg_hr", r[HeartRateRecord.BPM_AVG])
                .putOpt("resting_hr", r[RestingHeartRateRecord.BPM_AVG]))
        }
        return out
    }

    private suspend fun readSleep(client: HealthConnectClient, start: Instant, end: Instant): JSONArray {
        val out = JSONArray()
        for (s in readAll(client, SleepSessionRecord::class, start, end)) {
            val minutes = mutableMapOf<Int, Double>()
            for (st in s.stages) {
                val len = Duration.between(st.startTime, st.endTime).seconds / 60.0
                minutes[st.stage] = (minutes[st.stage] ?: 0.0) + len
            }
            fun m(vararg types: Int) = types.sumOf { minutes[it] ?: 0.0 }.takeIf { s.stages.isNotEmpty() }
            out.put(JSONObject()
                .put("start", s.startTime.toString())
                .put("end", s.endTime.toString())
                .putOpt("deep_min", m(SleepSessionRecord.STAGE_TYPE_DEEP))
                .putOpt("light_min", m(SleepSessionRecord.STAGE_TYPE_LIGHT, SleepSessionRecord.STAGE_TYPE_SLEEPING))
                .putOpt("rem_min", m(SleepSessionRecord.STAGE_TYPE_REM))
                .putOpt("awake_min", m(SleepSessionRecord.STAGE_TYPE_AWAKE,
                    SleepSessionRecord.STAGE_TYPE_AWAKE_IN_BED, SleepSessionRecord.STAGE_TYPE_OUT_OF_BED)))
        }
        return out
    }

    private suspend fun readFood(client: HealthConnectClient, start: Instant, end: Instant): JSONArray {
        val out = JSONArray()
        for (n in readAll(client, NutritionRecord::class, start, end)) {
            out.put(JSONObject()
                .put("id", n.metadata.id)
                .put("time", n.startTime.toString())
                .putOpt("name", n.name)
                .putOpt("meal", mealName(n.mealType))
                .putOpt("kcal", n.energy?.inKilocalories)
                .putOpt("protein_g", n.protein?.inGrams)
                .putOpt("fat_g", n.totalFat?.inGrams)
                .putOpt("carbs_g", n.totalCarbohydrate?.inGrams))
        }
        return out
    }

    private suspend fun readWeight(client: HealthConnectClient, start: Instant, end: Instant): JSONArray {
        val out = JSONArray()
        for (w in readAll(client, WeightRecord::class, start, end)) {
            out.put(JSONObject().put("time", w.time.toString()).put("kg", w.weight.inKilograms))
        }
        return out
    }

    private suspend fun <T : Record> readAll(
        client: HealthConnectClient, type: KClass<T>, start: Instant, end: Instant,
    ): List<T> {
        val all = mutableListOf<T>()
        var token: String? = null
        do {
            val page = client.readRecords(
                ReadRecordsRequest(type, TimeRangeFilter.between(start, end), pageToken = token)
            )
            all += page.records
            token = page.pageToken
        } while (token != null)
        return all
    }

    private fun mealName(type: Int): String? = when (type) {
        MealType.MEAL_TYPE_BREAKFAST -> "breakfast"
        MealType.MEAL_TYPE_LUNCH -> "lunch"
        MealType.MEAL_TYPE_DINNER -> "dinner"
        MealType.MEAL_TYPE_SNACK -> "snack"
        else -> null
    }

    private suspend fun post(url: String, token: String, body: String): String = withContext(Dispatchers.IO) {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = 10_000
            conn.readTimeout = 20_000
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            conn.setRequestProperty("Authorization", "Bearer $token")
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val text = (if (code < 400) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code >= 400) throw IOException("HTTP $code: $text")
            text
        } finally {
            conn.disconnect()
        }
    }
}
