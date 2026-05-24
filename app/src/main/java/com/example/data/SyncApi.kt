package com.example.data

import retrofit2.Response
import retrofit2.http.*

data class SyncDataMap(
    val notesJson: String,
    val clientTime: Long
)

data class SyncPayload(
    val name: String,
    val data: SyncDataMap
)

data class SyncUpdatePayload(
    val name: String,
    val data: SyncDataMap
)

data class SyncResponse(
    val id: String,
    val name: String?,
    val data: SyncDataMap?
)

interface SyncApi {
    @GET("objects/{id}")
    suspend fun getSyncData(@Path("id") id: String): Response<SyncResponse>

    @POST("objects")
    suspend fun createSyncData(@Body payload: SyncPayload): Response<SyncResponse>

    @PUT("objects/{id}")
    suspend fun updateSyncData(@Path("id") id: String, @Body payload: SyncUpdatePayload): Response<SyncResponse>
}
