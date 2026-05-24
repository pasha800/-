package com.example.data

import android.content.Context
import androidx.room.Room
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.util.UUID
import java.util.concurrent.TimeUnit

class NoteRepository(private val context: Context) {

    private val database = AppDatabase.getDatabase(context)
    private val noteDao = database.noteDao()

    private val moshi = Moshi.Builder()
        .addLast(KotlinJsonAdapterFactory())
        .build()

    private val listType = Types.newParameterizedType(List::class.java, NoteEntity::class.java)
    private val jsonAdapter = moshi.adapter<List<NoteEntity>>(listType)

    private val okHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .addInterceptor(HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        })
        .build()

    private val retrofit = Retrofit.Builder()
        .baseUrl("https://api.restful-api.dev/")
        .client(okHttpClient)
        .addConverterFactory(MoshiConverterFactory.create(moshi))
        .build()

    private val syncApi = retrofit.create(SyncApi::class.java)

    fun getAllNotesFlow(): Flow<List<NoteEntity>> = noteDao.getAllNotesFlow()

    suspend fun getNoteById(id: String): NoteEntity? = withContext(Dispatchers.IO) {
        noteDao.getNoteById(id)
    }

    suspend fun saveNote(title: String, content: String, existingId: String? = null): NoteEntity = withContext(Dispatchers.IO) {
        val now = System.currentTimeMillis()
        val note = if (existingId != null) {
            val existing = noteDao.getNoteById(existingId)
            NoteEntity(
                id = existingId,
                title = title,
                content = content,
                createdAt = existing?.createdAt ?: now,
                updatedAt = now,
                isDeleted = false
            )
        } else {
            NoteEntity(
                id = UUID.randomUUID().toString(),
                title = title,
                content = content,
                createdAt = now,
                updatedAt = now,
                isDeleted = false
            )
        }
        noteDao.insertOrUpdate(note)
        note
    }

    suspend fun softDeleteNote(id: String) = withContext(Dispatchers.IO) {
        noteDao.softDelete(id, System.currentTimeMillis())
    }

    /**
     * Creates a new cloud sync entry and returns the generated Sync Code.
     */
    suspend fun createCloudSync(): String = withContext(Dispatchers.IO) {
        val localNotes = noteDao.getAllNotesDirect()
        val json = jsonAdapter.toJson(localNotes)

        val payload = SyncPayload(
            name = "Markdown Notes Cloud Sync",
            data = SyncDataMap(
                notesJson = json,
                clientTime = System.currentTimeMillis()
            )
        )

        val response = syncApi.createSyncData(payload)
        if (response.isSuccessful) {
            val body = response.body() ?: throw Exception("Failed to create sync: empty body")
            return@withContext body.id
        } else {
            throw Exception("Failed to sync: ${response.errorBody()?.string() ?: response.message()}")
        }
    }

    /**
     * Performs a bidirectional sync between local database and the cloud sync code.
     * Returns true if successful and notes are updated.
     */
    suspend fun performSync(syncCode: String): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            // 1. Get cloud notes
            val response = syncApi.getSyncData(syncCode)
            if (!response.isSuccessful) {
                if (response.code() == 404) {
                    // Code doesn't exist on server yet, upload local database as first backup
                    val localNotes = noteDao.getAllNotesDirect()
                    val json = jsonAdapter.toJson(localNotes)
                    val updatePayload = SyncUpdatePayload(
                        name = "Markdown Notes Cloud Sync",
                        data = SyncDataMap(
                            notesJson = json,
                            clientTime = System.currentTimeMillis()
                        )
                    )
                    // Wait, our base URL doesn't have custom PUT unless we do createSyncData or updateSyncData
                    // If 404, we can attempt to register this custom syncCode using createSyncData
                    // Wait! api.restful-api.dev might not allow custom ID in POST if that ID is already generated, 
                    // but we can try to PUT or create. Actually, since we generated the syncCode dynamically via createCloudSync,
                    // we already have the ID in the cloud, so 404 is rare unless code is mistyped.
                    return@withContext Result.failure(Exception("Sync code not found in cloud (404)"))
                }
                return@withContext Result.failure(Exception("Cloud server responded with error: ${response.code()}"))
            }

            val syncResponse = response.body() ?: return@withContext Result.failure(Exception("Empty sync response"))
            val cloudDataMap = syncResponse.data ?: return@withContext Result.failure(Exception("No data found in sync response"))
            val cloudNotes = jsonAdapter.fromJson(cloudDataMap.notesJson) ?: emptyList()

            // 2. Load all local notes (including soft-deleted ones!)
            val localNotes = noteDao.getAllNotesDirect()
            val localMap = localNotes.associateBy { it.id }
            val cloudMap = cloudNotes.associateBy { it.id }

            val mergedNotes = mutableListOf<NoteEntity>()

            // Merge sets
            val allIds = localMap.keys + cloudMap.keys
            for (id in allIds) {
                val local = localMap[id]
                val cloud = cloudMap[id]

                when {
                    local != null && cloud != null -> {
                        // Conflict resolution: Last-Write-Wins based on updatedAt
                        if (cloud.updatedAt > local.updatedAt) {
                            mergedNotes.add(cloud)
                        } else {
                            mergedNotes.add(local)
                        }
                    }
                    local != null -> {
                        // Only exists in local
                        mergedNotes.add(local)
                    }
                    cloud != null -> {
                        // Only exists in cloud
                        mergedNotes.add(cloud)
                    }
                }
            }

            // 3. Save the merged dataset locally
            noteDao.insertAll(mergedNotes)

            // 4. Upload the unified merged dataset back to the cloud so all devices are synced
            val mergedJson = jsonAdapter.toJson(mergedNotes)
            val updatePayload = SyncUpdatePayload(
                name = "Markdown Notes Cloud Sync",
                data = SyncDataMap(
                    notesJson = mergedJson,
                    clientTime = System.currentTimeMillis()
                )
            )

            val updateResponse = syncApi.updateSyncData(syncCode, updatePayload)
            if (!updateResponse.isSuccessful) {
                return@withContext Result.failure(Exception("Failed to upload merged notes: ${updateResponse.code()}"))
            }

            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
