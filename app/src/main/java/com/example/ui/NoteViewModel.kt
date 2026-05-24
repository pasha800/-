package com.example.ui

import android.app.Application
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.data.NoteEntity
import com.example.data.NoteRepository
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

class NoteViewModel(application: Application) : AndroidViewModel(application) {

    private val repository = NoteRepository(application)
    private val prefs = application.getSharedPreferences("notes_prefs", Context.MODE_PRIVATE)

    // States
    private val _notesFlow = repository.getAllNotesFlow()
    
    val searchQuery = MutableStateFlow("")
    
    val allNotes: StateFlow<List<NoteEntity>> = _notesFlow
        .combine(searchQuery) { notes, query ->
            if (query.isBlank()) {
                notes
            } else {
                notes.filter {
                    it.title.contains(query, ignoreCase = true) || 
                    it.content.contains(query, ignoreCase = true)
                }
            }
        }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5000),
            initialValue = emptyList()
        )

    val selectedNoteId = MutableStateFlow<String?>(null)
    val currentEditTitle = MutableStateFlow("")
    val currentEditContent = MutableStateFlow("")
    val isEditing = MutableStateFlow(false)
    val isPreviewMode = MutableStateFlow(false) // Toggle inside edit mode: false = Edit, true = Markdown rendering

    val syncCode = MutableStateFlow("")
    val isSyncing = MutableStateFlow(false)
    val syncStatusMessage = MutableStateFlow("")

    init {
        // Load pairing code from settings on init
        val savedCode = prefs.getString("sync_code", "") ?: ""
        syncCode.value = savedCode
        if (savedCode.isNotBlank()) {
            syncStatusMessage.value = "Active sync code loaded: $savedCode"
        }
    }

    fun selectNote(noteId: String?) {
        viewModelScope.launch {
            selectedNoteId.value = noteId
            if (noteId != null) {
                val note = repository.getNoteById(noteId)
                if (note != null) {
                    currentEditTitle.value = note.title
                    currentEditContent.value = note.content
                }
                isEditing.value = true
                isPreviewMode.value = false
            } else {
                currentEditTitle.value = ""
                currentEditContent.value = ""
                isEditing.value = false
            }
        }
    }

    fun createAndSelectNewNote() {
        selectedNoteId.value = null
        currentEditTitle.value = ""
        currentEditContent.value = ""
        isEditing.value = true
        isPreviewMode.value = false
    }

    fun saveCurrentNote() {
        if (currentEditTitle.value.isBlank() && currentEditContent.value.isBlank()) {
            // Nothing to save
            isEditing.value = false
            return
        }
        viewModelScope.launch {
            val title = currentEditTitle.value.ifBlank { "Untitled Note" }
            val note = repository.saveNote(
                title = title,
                content = currentEditContent.value,
                existingId = selectedNoteId.value
            )
            selectedNoteId.value = note.id
            isEditing.value = false
            
            // Auto sync to cloud if a sync code is already set!
            val code = syncCode.value
            if (code.isNotBlank()) {
                syncWithCloud(code)
            }
        }
    }

    fun deleteNote(noteId: String) {
        viewModelScope.launch {
            repository.softDeleteNote(noteId)
            if (selectedNoteId.value == noteId) {
                selectedNoteId.value = null
                currentEditTitle.value = ""
                currentEditContent.value = ""
                isEditing.value = false
            }
            
            // Auto sync deletion to cloud if sync is configured!
            val code = syncCode.value
            if (code.isNotBlank()) {
                syncWithCloud(code)
            }
        }
    }

    fun appendMarkdownShortcut(syntax: String) {
        // Simple helper to insert formatting codes
        currentEditContent.value = currentEditContent.value + syntax
    }

    fun applyShortcutSelection(prefix: String, suffix: String = "") {
        // Append prefix/suffix to current editor content
        val currentText = currentEditContent.value
        currentEditContent.value = "$currentText\n$prefix $suffix"
    }

    fun saveSyncCode(code: String) {
        syncCode.value = code
        prefs.edit().putString("sync_code", code).apply()
        if (code.isNotBlank()) {
            syncStatusMessage.value = "Saved. Sync Code: $code"
        } else {
            syncStatusMessage.value = "Cloud Sync disconnected."
        }
    }

    fun generateSyncCode() {
        viewModelScope.launch {
            isSyncing.value = true
            syncStatusMessage.value = "Generating cloud vault..."
            try {
                val newCode = repository.createCloudSync()
                saveSyncCode(newCode)
                syncStatusMessage.value = "Vault created! Share this code: $newCode"
            } catch (e: Exception) {
                syncStatusMessage.value = "Error: ${e.message}"
            } finally {
                isSyncing.value = false
            }
        }
    }

    fun syncWithCloud(code: String) {
        if (code.isBlank()) {
            syncStatusMessage.value = "Please enter a valid Sync Code."
            return
        }
        viewModelScope.launch {
            isSyncing.value = true
            syncStatusMessage.value = "Synchronizing notes with cloud..."
            val result = repository.performSync(code)
            result.onSuccess {
                saveSyncCode(code)
                syncStatusMessage.value = "Sync successful! Database is up to date."
            }.onFailure { e ->
                syncStatusMessage.value = "Sync failed: ${e.message}"
            }
            isSyncing.value = false
        }
    }
}
