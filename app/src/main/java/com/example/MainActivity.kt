package com.example

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.ui.MarkdownParser
import com.example.ui.NoteViewModel
import com.example.data.NoteEntity
import com.example.ui.theme.MyApplicationTheme
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// ==========================================
// STRING LOCALIZATION ENGINE
// ==========================================
interface AppStrings {
    val markdownNotes: String
    val noNoteSelected: String
    val noNoteSelectedSub: String
    val createFreshNote: String
    val cloudVaultSync: String
    val cloudVaultSyncSub: String
    val pairingVaultSyncCode: String
    val pairingPlaceholder: String
    val connectAndSync: String
    val createKey: String
    val syncExplain: String
    val closePanel: String
    val noNotesFound: String
    val noNotesFoundSub: String
    val searchPlaceholder: String
    val unformattedEmptyPage: String
    val untitledDocument: String
    val searchNoResults: String
    val searchNoResultsSub: String
    val writeTab: String
    val previewTab: String
    val saveBtn: String
    val noteTitlePlaceholder: String
    val markdownPlaceholder: String
    val boldDesc: String
    val italicDesc: String
    val h1Desc: String
    val h2Desc: String
    val quoteDesc: String
    val listDesc: String
    val codeDesc: String
    val syncedBadge: String
}

object KurdishStrings : AppStrings {
    override val markdownNotes = "تێبینییەکانی مارکداون"
    override val noNoteSelected = "هیچ تێبینییەک دیاری نەکراوە"
    override val noNoteSelectedSub = "تێبینییە کۆنەکان دەستکاری بکە یان لاپەڕەیەکی نوێی مارکداون بنووسە."
    override val createFreshNote = "تێبینی نوێ بنووسە"
    override val cloudVaultSync = "هاوگونجاندنی هەور"
    override val cloudVaultSyncSub = "تێبینییەکانت بە پارێزراوی لەگەڵ کۆمپیوتەر، تابلێت، و مۆبایلەکانی ترت هاوکات بکە."
    override val pairingVaultSyncCode = "کۆدی هاوگونجاندنی هەور"
    override val pairingPlaceholder = "بۆ نموونە ff8081817e4cfba..."
    override val connectAndSync = "پەیوەستکردن و هاوکاتکردن"
    override val createKey = "دروستکردنی کۆد"
    override val syncExplain = "بۆ هاوگونجاندنی ئامێرەکانی تر، کۆدی هاوگونجاندنی سەرەوە کۆپی بکە و لە بەشی کۆدی هاوگونجاندنی ئەوانی تر دایبنێ."
    override val closePanel = "داخستنی پانێڵ"
    override val noNotesFound = "هیچ تێبینییەکی مارکداون نەدۆزرایەوە."
    override val noNotesFoundSub = "دەست پێ بکە بە نووسینی یەکەم تێبینیت لێرەدا یان هاوگونجاندن چالاک بکە."
    override val searchPlaceholder = "گەڕان لە ناونیشان یان ناوەڕۆک..."
    override val unformattedEmptyPage = "لاپەڕەیەکی بەتاڵ بەبێ ناوەڕۆک..."
    override val untitledDocument = "بەڵگەی بێ ناونیشان"
    override val searchNoResults = "هیچ ئەنجامێک بۆ ئەم گەڕانە نەدۆزرایەوە."
    override val searchNoResultsSub = "هەوڵ بدە گەڕان بە وشەی سادەتر یان جیاوازتر بکەیت."
    override val writeTab = "نووسین"
    override val previewTab = "پێشبینین"
    override val saveBtn = "پاشەکەوت"
    override val noteTitlePlaceholder = "ناونیشانی تێبینی"
    override val markdownPlaceholder = "بە مارکداون بنووسە...\n\n# سەر دێڕ\n**دەقی تۆخ**\n*دەقی لار*\n- لیستەکان\n`کۆدی ناوەکی`\n> وتە پێشنیارکراوەکان"
    override val boldDesc = "تۆخ"
    override val italicDesc = "لار"
    override val h1Desc = "سەردێڕی ١"
    override val h2Desc = "سەردێڕی ٢"
    override val quoteDesc = "وتە"
    override val listDesc = "لیست"
    override val codeDesc = "کۆد"
    override val syncedBadge = "هاوکات کرا"
}

object EnglishStrings : AppStrings {
    override val markdownNotes = "Markdown Notes"
    override val noNoteSelected = "No Note Selected"
    override val noNoteSelectedSub = "Edit existing notes or write a beautiful new markdown page instantly."
    override val createFreshNote = "Create Fresh Note"
    override val cloudVaultSync = "Cloud Vault Sync"
    override val cloudVaultSyncSub = "Synchronize all notes securely across all of your other computers, tablets, and phones."
    override val pairingVaultSyncCode = "Pairing Vault Sync Code"
    override val pairingPlaceholder = "e.g. ff8081817e4cfba..."
    override val connectAndSync = "Connect & Sync"
    override val createKey = "Create Key"
    override val syncExplain = "To sync other devices, copy your Vault Sync Code above and enter it in their Sync Code fields."
    override val closePanel = "Close Panel"
    override val noNotesFound = "No markdown notes found."
    override val noNotesFoundSub = "Create a markdown note or configure cloud sync."
    override val searchPlaceholder = "Search title or markdown body..."
    override val unformattedEmptyPage = "Unformatted empty page..."
    override val untitledDocument = "Untitled Document"
    override val searchNoResults = "No search results matched."
    override val searchNoResultsSub = "Try searching for simpler words."
    override val writeTab = "Write"
    override val previewTab = "Preview"
    override val saveBtn = "Save"
    override val noteTitlePlaceholder = "Note Title"
    override val markdownPlaceholder = "Express yourself in Markdown...\n\n# Header\n**bold text**\n*italic text*\n- List elements\n`inline code`\n> Blockquotes"
    override val boldDesc = "Bold"
    override val italicDesc = "Italic"
    override val h1Desc = "Heading 1"
    override val h2Desc = "Heading 2"
    override val quoteDesc = "Blockquote"
    override val listDesc = "Bullet List"
    override val codeDesc = "Code"
    override val syncedBadge = "SYNCED"
}

fun mapSyncStatusMessage(msg: String, isKurdish: Boolean): String {
    if (!isKurdish) return msg
    return when {
        msg.startsWith("Active sync code loaded:") -> {
            val code = msg.substringAfter("Active sync code loaded:").trim()
            "کۆدی هاوگونجاندنی چالاک لۆد کرا: $code"
        }
        msg.startsWith("Saved. Sync Code:") -> {
            val code = msg.substringAfter("Saved. Sync Code:").trim()
            "پاشەکەوت کرا. کۆدی هاوگونجاندن: $code"
        }
        msg == "Cloud Sync disconnected." -> "پەیوەندی هاوگونجاندنی هەور پچڕا."
        msg == "Generating cloud vault..." -> "دروستکردنی کۆدی هاوگونجاندن..."
        msg.startsWith("Vault created! Share this code:") -> {
            val code = msg.substringAfter("Vault created! Share this code:").trim()
            "ناسنامەی هەور دروستکرا! ئەم کۆدە هاوبەش بکە:\n$code"
        }
        msg == "Synchronizing notes with cloud..." -> "هاوکاتکردنی تێبینییەکان لەگەڵ تیمی هەور..."
        msg == "Sync successful! Database is up to date." -> "هاوکاتکردن سەرکەوتوو بوو! تێبینییەکان نوێکرانەوە."
        msg.startsWith("Sync failed:") -> {
            val reason = msg.substringAfter("Sync failed:").trim()
            "هاوگونجاندن سەرنەکەوت: $reason"
        }
        msg == "Please enter a valid Sync Code." -> "تکایە کۆدێکی هاوگونجاندنی دروست داخڵ بکە."
        msg.startsWith("Error:") -> {
            val reason = msg.substringAfter("Error:").trim()
            "کێشەیەک ڕوویدا: $reason"
        }
        else -> msg
    }
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MyApplicationTheme {
                MainAppScreen()
            }
        }
    }
}

@Composable
fun MainAppScreen(
    viewModel: NoteViewModel = viewModel()
) {
    var isKurdish by remember { mutableStateOf(true) }
    val strings = if (isKurdish) KurdishStrings else EnglishStrings

    CompositionLocalProvider(
        LocalLayoutDirection provides (if (isKurdish) LayoutDirection.Rtl else LayoutDirection.Ltr)
    ) {
        // Scaffold takes care of margins and system navigation bars
        Scaffold(
            modifier = Modifier.fillMaxSize()
        ) { innerPadding ->
            // Use local scale/dimensions to handle adaptive canonical layouts
            val configuration = LocalConfiguration.current
            val screenWidthDp = configuration.screenWidthDp
            val isWideScreen = screenWidthDp >= 600

            Box(
                modifier = Modifier
                    .padding(innerPadding)
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.background)
            ) {
                if (isWideScreen) {
                    // Expanded screen layout: canonical side-by-side list & editor view
                    WideScreenLayout(viewModel, isKurdish = isKurdish, strings = strings, onLanguageToggle = { isKurdish = !isKurdish })
                } else {
                    // Compact screen layout: single-pane list vs editor state machine
                    CompactScreenLayout(viewModel, isKurdish = isKurdish, strings = strings, onLanguageToggle = { isKurdish = !isKurdish })
                }
            }
        }
    }
}

// ==========================================
// 1. COMPACT SCREEN (MOBILE-FIRST) STATE-MACHINE LAYOUT
// ==========================================
@Composable
fun CompactScreenLayout(
    viewModel: NoteViewModel,
    isKurdish: Boolean,
    strings: AppStrings,
    onLanguageToggle: () -> Unit
) {
    val isEditing by viewModel.isEditing.collectAsState()
    
    // Animate transitions between Notes List and Editor
    AnimatedContent(
        targetState = isEditing,
        transitionSpec = {
            if (targetState) {
                (slideInHorizontally { width -> width } + fadeIn()).togetherWith(
                    slideOutHorizontally { width -> -width } + fadeOut())
            } else {
                (slideInHorizontally { width -> -width } + fadeIn()).togetherWith(
                    slideOutHorizontally { width -> width } + fadeOut())
            }
        },
        label = "ScreenTransition"
    ) { editing ->
        if (editing) {
            NoteEditorScreen(viewModel = viewModel, isWideScreen = false, isKurdish = isKurdish, strings = strings)
        } else {
            NotesListScreen(viewModel = viewModel, isWideScreen = false, isKurdish = isKurdish, strings = strings, onLanguageToggle = onLanguageToggle)
        }
    }
}

// ==========================================
// 2. WIDE SCREEN (TABLET/DOCK) LAYOUT
// ==========================================
@Composable
fun WideScreenLayout(
    viewModel: NoteViewModel,
    isKurdish: Boolean,
    strings: AppStrings,
    onLanguageToggle: () -> Unit
) {
    Row(
        modifier = Modifier.fillMaxSize()
    ) {
        // Left Column: Note list taking up 35%
        Box(
            modifier = Modifier
                .fillMaxHeight()
                .weight(0.35f)
                .border(1.dp, MaterialTheme.colorScheme.surfaceVariant)
        ) {
            NotesListScreen(viewModel = viewModel, isWideScreen = true, isKurdish = isKurdish, strings = strings, onLanguageToggle = onLanguageToggle)
        }
        
        // Right Column: Active note detail taking up 65%
        Box(
            modifier = Modifier
                .fillMaxHeight()
                .weight(0.65f)
                .background(MaterialTheme.colorScheme.background)
        ) {
            val isEditing by viewModel.isEditing.collectAsState()
            if (isEditing) {
                NoteEditorScreen(viewModel = viewModel, isWideScreen = true, isKurdish = isKurdish, strings = strings)
            } else {
                // Beautiful empty/inactive detail state
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(32.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center
                ) {
                    Icon(
                        imageVector = Icons.Default.Description,
                        contentDescription = strings.noNoteSelected,
                        tint = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f),
                        modifier = Modifier.size(72.dp)
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Text(
                        text = strings.noNoteSelected,
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onBackground
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = strings.noNoteSelectedSub,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.outline,
                        modifier = Modifier.widthIn(max = 300.dp),
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center
                    )
                    Spacer(modifier = Modifier.height(24.dp))
                    Button(
                        onClick = { viewModel.createAndSelectNewNote() },
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
                    ) {
                        Icon(Icons.Default.Add, contentDescription = "Add")
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(strings.createFreshNote)
                    }
                }
            }
        }
    }
}

// ==========================================
// 3. INTERNAL VIEW COMPONENT: NOTES LIST SCREEN
// ==========================================
@Composable
fun NotesListScreen(
    viewModel: NoteViewModel,
    isWideScreen: Boolean,
    isKurdish: Boolean,
    strings: AppStrings,
    onLanguageToggle: () -> Unit
) {
    val notes by viewModel.allNotes.collectAsState()
    val searchQuery by viewModel.searchQuery.collectAsState()
    val selectedNoteId by viewModel.selectedNoteId.collectAsState()
    
    var showSyncDialog by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier.fillMaxSize()
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
        ) {
            // Elegant App Header
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        imageVector = Icons.Default.Book,
                        contentDescription = strings.markdownNotes,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(32.dp)
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Text(
                        text = strings.markdownNotes,
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onBackground
                    )
                }
                
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    val currentSyncCode by viewModel.syncCode.collectAsState()
                    if (currentSyncCode.isNotBlank()) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier
                                .clip(RoundedCornerShape(100.dp))
                                .background(MaterialTheme.colorScheme.tertiary.copy(alpha = 0.85f))
                                .padding(horizontal = 10.dp, vertical = 4.dp)
                        ) {
                            Icon(
                                imageVector = Icons.Default.CloudDone,
                                contentDescription = "Synced successfully badge icon",
                                tint = MaterialTheme.colorScheme.onSecondary,
                                modifier = Modifier.size(14.dp)
                            )
                            Spacer(modifier = Modifier.width(4.dp))
                            Text(
                                text = strings.syncedBadge,
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onSecondary,
                                fontSize = 10.sp
                            )
                        }
                    }
                    
                    // Language Switch Button
                    TextButton(
                        onClick = onLanguageToggle,
                        colors = ButtonDefaults.textButtonColors(
                            contentColor = MaterialTheme.colorScheme.primary
                        ),
                        modifier = Modifier.testTag("language_toggle_button")
                    ) {
                        Icon(
                            imageVector = Icons.Default.Language,
                            contentDescription = "Switch language",
                            modifier = Modifier.size(18.dp)
                        )
                        Spacer(modifier = Modifier.width(4.dp))
                        Text(
                            text = if (isKurdish) "English" else "کوردی",
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Bold
                        )
                    }

                    // Cloud Sync Launcher Button inside header
                    IconButton(
                        onClick = { showSyncDialog = true },
                        modifier = Modifier.testTag("sync_panel_button")
                    ) {
                        Icon(
                            imageVector = Icons.Default.CloudSync,
                            contentDescription = "Cloud Vault Sync Settings",
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(28.dp)
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Inline Search Bar
            OutlinedTextField(
                value = searchQuery,
                onValueChange = { viewModel.searchQuery.value = it },
                placeholder = { Text(strings.searchPlaceholder) },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = "Search icon") },
                trailingIcon = {
                    if (searchQuery.isNotEmpty()) {
                        IconButton(onClick = { viewModel.searchQuery.value = "" }) {
                            Icon(Icons.Default.Close, contentDescription = "Clear search")
                        }
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("search_bar"),
                shape = RoundedCornerShape(12.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = MaterialTheme.colorScheme.primary,
                    unfocusedBorderColor = MaterialTheme.colorScheme.surfaceVariant
                ),
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search)
            )

            Spacer(modifier = Modifier.height(16.dp))

            // Dynamic Notes List or Cozy Empty State
            if (notes.isEmpty()) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    contentAlignment = Alignment.Center
                ) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Icon(
                            imageVector = Icons.Default.EditNote,
                            contentDescription = "Writer Empty State Pencil icon",
                            tint = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f),
                            modifier = Modifier.size(80.dp)
                        )
                        Spacer(modifier = Modifier.height(16.dp))
                        Text(
                            text = if (searchQuery.isBlank()) strings.noNotesFound else strings.searchNoResults,
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = FontWeight.Medium,
                            color = MaterialTheme.colorScheme.outline
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = if (searchQuery.isBlank()) strings.noNotesFoundSub else strings.searchNoResultsSub,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.outline.copy(alpha = 0.8f)
                        )
                    }
                }
            } else {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    items(notes, key = { it.id }) { note ->
                        val isSelected = isWideScreen && note.id == selectedNoteId
                        NoteListItem(
                            note = note,
                            isSelected = isSelected,
                            isKurdish = isKurdish,
                            onSelect = { viewModel.selectNote(note.id) },
                            onDelete = { viewModel.deleteNote(note.id) }
                        )
                    }
                }
            }
        }

        // Float standard FAB on Compact Screens ONLY (on Wide screen we put CTA inside right pane)
        if (!isWideScreen) {
            FloatingActionButton(
                onClick = { viewModel.createAndSelectNewNote() },
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(24.dp)
                    .testTag("add_note_fab"),
                containerColor = MaterialTheme.colorScheme.primary,
                contentColor = MaterialTheme.colorScheme.onPrimary
            ) {
                Icon(
                    imageVector = Icons.Default.Add,
                    contentDescription = "Create blank markdown note button",
                    modifier = Modifier.size(28.dp)
                )
            }
        }
    }

    // Cloud Vault Peer-to-Peer Pairing Dialogue Window
    if (showSyncDialog) {
        CloudSyncDialog(viewModel = viewModel, isKurdish = isKurdish, strings = strings) {
            showSyncDialog = false
        }
    }
}

// ==========================================
// 4. SUBCOMPONENT: CLOUD SYNC SETTINGS DIALOGUE
// ==========================================
@Composable
fun CloudSyncDialog(
    viewModel: NoteViewModel,
    isKurdish: Boolean,
    strings: AppStrings,
    onDismiss: () -> Unit
) {
    val syncCode by viewModel.syncCode.collectAsState()
    val isSyncing by viewModel.isSyncing.collectAsState()
    val statusMsg by viewModel.syncStatusMessage.collectAsState()
    
    var tempCodeInput by remember { mutableStateOf(syncCode) }

    Dialog(onDismissRequest = onDismiss) {
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(4.dp)
                .testTag("sync_dialog_card"),
            shape = RoundedCornerShape(28.dp),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            elevation = CardDefaults.cardElevation(defaultElevation = 8.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                // Header with sync illustration icon
                Icon(
                    imageVector = Icons.Default.CloudSync,
                    contentDescription = "Cloud Icon Drawer",
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(48.dp)
                )
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = strings.cloudVaultSync,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface
                )
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = strings.cloudVaultSyncSub,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center
                )

                Spacer(modifier = Modifier.height(16.dp))

                // Input Code Field
                OutlinedTextField(
                    value = tempCodeInput,
                    onValueChange = { tempCodeInput = it },
                    label = { Text(strings.pairingVaultSyncCode) },
                    placeholder = { Text(strings.pairingPlaceholder) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("sync_input_code"),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = MaterialTheme.colorScheme.primary,
                        unfocusedBorderColor = MaterialTheme.colorScheme.surfaceVariant
                    ),
                    singleLine = true,
                    enabled = !isSyncing
                )

                Spacer(modifier = Modifier.height(12.dp))

                // Action controls row
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    // Connect/Sync Button
                    Button(
                        onClick = { viewModel.syncWithCloud(tempCodeInput) },
                        modifier = Modifier
                            .weight(1f)
                            .testTag("connect_sync_button"),
                        enabled = tempCodeInput.isNotBlank() && !isSyncing,
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
                    ) {
                        Text(strings.connectAndSync)
                    }

                    // Create New Code Button
                    FilledTonalButton(
                        onClick = { 
                            viewModel.generateSyncCode()
                        },
                        modifier = Modifier
                            .weight(1f)
                            .testTag("generate_vault_button"),
                        enabled = !isSyncing
                    ) {
                        Text(strings.createKey)
                    }
                }

                // If code exists, show pairing details
                if (syncCode.isNotBlank()) {
                    Spacer(modifier = Modifier.height(6.dp))
                    Text(
                        text = strings.syncExplain,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center
                    )
                }

                // Real-time server connection logs
                if (statusMsg.isNotBlank()) {
                    Spacer(modifier = Modifier.height(16.dp))
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(MaterialTheme.colorScheme.surfaceVariant)
                            .padding(12.dp)
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (isSyncing) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(16.dp),
                                    strokeWidth = 2.dp,
                                    color = MaterialTheme.colorScheme.primary
                                )
                                Spacer(modifier = Modifier.width(10.dp))
                            }
                            Text(
                                text = mapSyncStatusMessage(statusMsg, isKurdish),
                                fontFamily = FontFamily.Monospace,
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Dismiss Close trigger button
                TextButton(
                    onClick = {
                        // Keep state sync setting input matched
                        tempCodeInput = viewModel.syncCode.value
                        onDismiss()
                    },
                    modifier = Modifier.align(Alignment.End)
                ) {
                    Text(strings.closePanel)
                }
            }
        }
    }
}

// ==========================================
// 5. SUBCOMPONENT: INDIVIDUAL NOTE LIST ITEM
// ==========================================
@Composable
fun NoteListItem(
    note: NoteEntity,
    isSelected: Boolean,
    isKurdish: Boolean,
    onSelect: () -> Unit,
    onDelete: () -> Unit
) {
    val formatter = remember { SimpleDateFormat("MMM dd, yyyy · hh:mm a", Locale.getDefault()) }
    val formattedDate = remember(note.updatedAt) { formatter.format(Date(note.updatedAt)) }
    
    // Automatically parse hashtags from note body content to show tags like in design format HTML
    val parsedTags = remember(note.content) {
        val matches = Regex("#([a-zA-Z0-9_-]+)").findAll(note.content)
        matches.map { it.groupValues[1] }.distinct().take(3).toList()
    }
    
    // Smooth outline highlighting if selected (on tablets) to match Clean Minimalism border styling
    val borderModifier = if (isSelected) {
        Modifier.border(2.dp, MaterialTheme.colorScheme.primary, RoundedCornerShape(24.dp))
    } else {
        Modifier.border(1.dp, MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(24.dp))
    }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("note_item_${note.id}")
            .then(borderModifier)
            .clickable { onSelect() },
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (isSelected) MaterialTheme.colorScheme.primary.copy(alpha = 0.05f) else MaterialTheme.colorScheme.surface
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Column(
                modifier = Modifier.weight(1f)
            ) {
                val displayTitle = if (note.title == "Untitled Note" || note.title == "Untitled Document" || note.title.isBlank()) {
                    if (isKurdish) "تێبینی بێ ناونیشان" else "Untitled Note"
                } else {
                    note.title
                }
                Text(
                    text = displayTitle,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                
                Spacer(modifier = Modifier.height(6.dp))
                
                // Show raw snippet, filtering out leading hashtags
                val snippetText = note.content.replace(Regex("#+\\s"), "").take(120)
                Text(
                    text = snippetText.ifBlank { if (isKurdish) "لاپەڕەیەکی بەتاڵ بەبێ ناوەڕۆک..." else "Unformatted empty page..." },
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.outline,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )

                // Render meta tags (Tailwind tag style)
                if (parsedTags.isNotEmpty()) {
                    Spacer(modifier = Modifier.height(10.dp))
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        parsedTags.forEach { tag ->
                            Box(
                                modifier = Modifier
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(MaterialTheme.colorScheme.secondary.copy(alpha = 0.2f))
                                    .padding(horizontal = 8.dp, vertical = 3.dp)
                            ) {
                                Text(
                                    text = "#$tag",
                                    color = MaterialTheme.colorScheme.onSecondary,
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 10.sp
                                )
                            }
                        }
                    }
                }

                Spacer(modifier = Modifier.height(8.dp))
                
                Text(
                    text = formattedDate,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline.copy(alpha = 0.8f)
                )
            }
            
            // Soft delete action
            IconButton(
                onClick = { onDelete() },
                modifier = Modifier.padding(start = 8.dp)
            ) {
                Icon(
                    imageVector = Icons.Default.Delete,
                    contentDescription = "Remove note button",
                    tint = MaterialTheme.colorScheme.error.copy(alpha = 0.7f),
                    modifier = Modifier.size(20.dp)
                )
            }
        }
    }
}

// ==========================================
// 6. INTERNAL VIEW COMPONENT: NOTE EDITOR SCREEN
// ==========================================
@Composable
fun NoteEditorScreen(
    viewModel: NoteViewModel,
    isWideScreen: Boolean,
    isKurdish: Boolean,
    strings: AppStrings
) {
    val title by viewModel.currentEditTitle.collectAsState()
    val content by viewModel.currentEditContent.collectAsState()
    val isPreviewMode by viewModel.isPreviewMode.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.surface)
    ) {
        // Simple editor bar
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                // If not wide screen, show back arrow to return to Note List
                if (!isWideScreen) {
                    IconButton(
                        onClick = { viewModel.saveCurrentNote() },
                        modifier = Modifier.testTag("editor_back_button")
                    ) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                }
                
                // Mode Toggle: Write vs Preview
                Row(
                    modifier = Modifier
                        .clip(RoundedCornerShape(20.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                        .padding(2.dp)
                ) {
                    Text(
                        text = strings.writeTab,
                        modifier = Modifier
                            .clip(RoundedCornerShape(18.dp))
                            .background(if (!isPreviewMode) MaterialTheme.colorScheme.primary else Color.Transparent)
                            .clickable { viewModel.isPreviewMode.value = false }
                            .padding(horizontal = 14.dp, vertical = 6.dp),
                        color = if (!isPreviewMode) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                    Text(
                        text = strings.previewTab,
                        modifier = Modifier
                            .clip(RoundedCornerShape(18.dp))
                            .background(if (isPreviewMode) MaterialTheme.colorScheme.primary else Color.Transparent)
                            .clickable { viewModel.isPreviewMode.value = true }
                            .padding(horizontal = 14.dp, vertical = 6.dp),
                        color = if (isPreviewMode) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                }
            }

            // Save Action Button
            Button(
                onClick = { viewModel.saveCurrentNote() },
                modifier = Modifier.testTag("editor_save_button"),
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
            ) {
                Icon(
                    imageVector = Icons.Default.Done,
                    contentDescription = "Save edit button",
                    modifier = Modifier.size(18.dp)
                )
                Spacer(modifier = Modifier.width(6.dp))
                Text(strings.saveBtn)
            }
        }

        Divider(color = MaterialTheme.colorScheme.surfaceVariant)

        // Body Elements
        if (isPreviewMode) {
            // HIGH-FIDELITY LIVE PREVIEW RENDERER
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .verticalScroll(rememberScrollState())
                    .padding(20.dp)
                    .testTag("markdown_preview_scroll")
            ) {
                // Large Document Heading
                Text(
                    text = title.ifBlank { strings.untitledDocument },
                    style = MaterialTheme.typography.headlineLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface
                )
                Spacer(modifier = Modifier.height(14.dp))
                Divider(color = MaterialTheme.colorScheme.surfaceVariant, thickness = 2.dp)
                Spacer(modifier = Modifier.height(14.dp))

                // Beautiful custom parsed AnnotatedString body
                val parsedContent = MarkdownParser.parse(
                    text = content, 
                    colorScheme = MaterialTheme.colorScheme
                )
                Text(
                    text = parsedContent,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    lineHeight = 26.sp
                )
            }
        } else {
            // WRITE EDITING EDITOR TEXT FIELDS
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .padding(horizontal = 16.dp, vertical = 8.dp)
            ) {
                // Title Field
                TextField(
                    value = title,
                    onValueChange = { viewModel.currentEditTitle.value = it },
                    placeholder = {
                        Text(
                            text = strings.noteTitlePlaceholder,
                            style = MaterialTheme.typography.headlineSmall,
                            color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f)
                        )
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("editor_title_input"),
                    textStyle = MaterialTheme.typography.headlineSmall.copy(fontWeight = FontWeight.Bold),
                    colors = TextFieldDefaults.colors(
                        focusedContainerColor = Color.Transparent,
                        unfocusedContainerColor = Color.Transparent,
                        disabledContainerColor = Color.Transparent,
                        focusedIndicatorColor = Color.Transparent,
                        unfocusedIndicatorColor = Color.Transparent
                    ),
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next)
                )

                Divider(color = MaterialTheme.colorScheme.surfaceVariant)

                // Body content field supporting multi-lines
                TextField(
                    value = content,
                    onValueChange = { viewModel.currentEditContent.value = it },
                    placeholder = {
                        Text(
                            strings.markdownPlaceholder,
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f)
                        )
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f)
                        .testTag("editor_content_input"),
                    textStyle = MaterialTheme.typography.bodyLarge,
                    colors = TextFieldDefaults.colors(
                        focusedContainerColor = Color.Transparent,
                        unfocusedContainerColor = Color.Transparent,
                        disabledContainerColor = Color.Transparent,
                        focusedIndicatorColor = Color.Transparent,
                        unfocusedIndicatorColor = Color.Transparent
                    )
                )

                // BOTTOM SHORTCUT FORMATTING TOOLBAR
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp)
                        .clip(RoundedCornerShape(16.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                        .padding(horizontal = 6.dp, vertical = 2.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(
                        modifier = Modifier.weight(1f),
                        horizontalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        ShortcutButton(label = "B", description = strings.boldDesc) {
                            viewModel.applyShortcutSelection("**", "**")
                        }
                        ShortcutButton(label = "I", description = strings.italicDesc) {
                            viewModel.applyShortcutSelection("*", "*")
                        }
                        ShortcutButton(label = "#", description = strings.h1Desc) {
                            viewModel.applyShortcutSelection("# ")
                        }
                        ShortcutButton(label = "##", description = strings.h2Desc) {
                            viewModel.applyShortcutSelection("## ")
                        }
                        ShortcutButton(label = ">", description = strings.quoteDesc) {
                            viewModel.applyShortcutSelection("> ")
                        }
                        ShortcutButton(label = "-", description = strings.listDesc) {
                            viewModel.applyShortcutSelection("- ")
                        }
                        ShortcutButton(label = "`", description = strings.codeDesc) {
                            viewModel.applyShortcutSelection("`", "`")
                        }
                    }
                }
            }
        }
    }
}

// Simple Helper state scroll
@Composable
fun rememberScrollState(): androidx.compose.foundation.ScrollState {
    return androidx.compose.foundation.rememberScrollState()
}

// Bottom shortcut element representation
@Composable
fun ShortcutButton(
    label: String,
    description: String,
    onClick: () -> Unit
) {
    TextButton(
        onClick = onClick,
        modifier = Modifier
            .minimumInteractiveComponentSize()
            .testTag("shortcut_$label"),
        colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.onSurfaceVariant)
    ) {
        Text(
            text = label,
            fontWeight = FontWeight.Bold,
            fontSize = 14.sp
        )
    }
}
