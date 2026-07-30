package app.swarmdeck

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.foundation.background
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.swarmdeck.ui.*
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * The whole phone app: the desktop's views, laid out for a narrow screen.
 * Board / Needs you / Dashboard / More, plus the card surface which carries the
 * same operations as the desktop peek panel.
 */
class MainActivity : ComponentActivity() {

    private val pairedFromIntent = mutableStateOf(0)
    // a card id from a tapped push notification (PushService puts "track" extra) -
    // AppRoot opens that card once the board has loaded.
    private val openTrackFromIntent = mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        HubStore.init(this)
        consumePairingIntent(intent)
        openTrackFromIntent.value = intent?.getStringExtra("track")?.ifBlank { null }
        setContent { SwarmTheme { AppRoot(pairedFromIntent.value, openTrackFromIntent) } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent); setIntent(intent); consumePairingIntent(intent)
        intent.getStringExtra("track")?.ifBlank { null }?.let { openTrackFromIntent.value = it }
    }

    /** A scanned pairing QR (https app link, or the swarmdeck:// fallback). */
    private fun consumePairingIntent(intent: Intent?): Boolean {
        val data = intent?.data ?: return false
        val isAppLink = data.scheme == "https" && data.path?.startsWith("/pair") == true
        val isCustom = data.scheme == "swarmdeck" && data.host == "pair"
        if (!isAppLink && !isCustom) return false
        if (data.getQueryParameter("c").isNullOrEmpty()) return false
        // pass the whole link: for an app link the origin carries the relay url
        return if (HubStore.applyPairingCode(data.toString())) { pairedFromIntent.value++; true } else false
    }
}

private enum class Tab(val label: String) { BOARD("Board"), NEEDS("Needs you"), DASH("Dashboard"), MORE("More") }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppRoot(pairNonce: Int = 0, openTrackState: androidx.compose.runtime.MutableState<String?>? = null) {
    val scope = rememberCoroutineScope()
    var tab by remember { mutableStateOf(Tab.BOARD) }
    var moreView by remember { mutableStateOf<String?>(null) }   // processes|history|chat|settings
    var open by remember { mutableStateOf<Track?>(null) }
    var tracks by remember { mutableStateOf<List<Track>>(emptyList()) }
    var metrics by remember { mutableStateOf<Metrics?>(null) }
    var laneLabels by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    var toastMsg by remember { mutableStateOf<String?>(null) }
    var loadErr by remember { mutableStateOf<String?>(null) }
    var showNew by remember { mutableStateOf(false) }
    var chatOpen by remember { mutableStateOf(false) }
    var reload by remember { mutableStateOf(0) }

    val toast: (String) -> Unit = { toastMsg = it }
    LaunchedEffect(toastMsg) { if (toastMsg != null) { delay(2600); toastMsg = null } }

    // deep-link from a tapped push notification: open that card once it's loaded
    val pendingTrack = openTrackState?.value
    LaunchedEffect(pendingTrack, tracks) {
        val id = pendingTrack ?: return@LaunchedEffect
        tracks.firstOrNull { it.id == id }?.let { open = it; tab = Tab.BOARD; openTrackState?.value = null }
    }

    // self-update: one silent check per app start against the relay host
    val ctx = androidx.compose.ui.platform.LocalContext.current
    var update by remember { mutableStateOf<Updater.Info?>(null) }
    var updProgress by remember { mutableStateOf<Float?>(null) }
    LaunchedEffect(pairNonce) { update = Updater.check(ctx) }

    // push: ask once for the notification permission (API 33+), then announce
    // the FCM token to the daemon - pushes are sealed to this device's keys
    val askNotif = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) {}
    LaunchedEffect(pairNonce) {
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            androidx.core.content.ContextCompat.checkSelfPermission(
                ctx, android.Manifest.permission.POST_NOTIFICATIONS) !=
                android.content.pm.PackageManager.PERMISSION_GRANTED)
            askNotif.launch(android.Manifest.permission.POST_NOTIFICATIONS)
    }
    // Paseo's lesson: announce the push token on EVERY connection, not once at
    // launch - at first launch the app is typically not yet paired, and a
    // one-shot registration silently loses push forever. Retries until it
    // lands, then stops.
    var pushRegistered by remember { mutableStateOf(false) }
    LaunchedEffect(pairNonce) {
        while (!pushRegistered) {
            if (DaemonClient.configured()) runCatching {
                val tok = kotlinx.coroutines.suspendCancellableCoroutine<String> { cont ->
                    com.google.firebase.messaging.FirebaseMessaging.getInstance().token
                        .addOnSuccessListener { cont.resume(it) {} }
                        .addOnFailureListener { cont.cancel(it) }
                }
                DaemonClient.registerPushToken(tok)
                pushRegistered = true
            }
            if (!pushRegistered) delay(8000)
        }
    }

    // board data, refreshed on a light poll so the phone tracks the desktop
    LaunchedEffect(reload, pairNonce) {
        while (true) {
            if (DaemonClient.configured()) {
                runCatching { DaemonClient.tracks() }
                    .onSuccess { tracks = it; loadErr = null }
                    .onFailure { loadErr = it.message }
                runCatching { DaemonClient.metrics() }.onSuccess { metrics = it }
                runCatching { DaemonClient.settings() }.onSuccess { s ->
                    val p = s.optJSONObject("policy")?.optJSONObject("lane_labels")
                    if (p != null) laneLabels = p.keys().asSequence().associateWith { p.optString(it) }
                }
            }
            delay(6000)
        }
    }

    open?.let { t ->
        CardScreen(t, onBack = { open = null }, onChanged = { reload++ }, toast = toast)
        return
    }

    Scaffold(
        containerColor = Tok.canvas,
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Tok.surface1, titleContentColor = Tok.txtPrimary),
                title = {
                    Text(moreView?.replaceFirstChar { it.uppercase() } ?: tab.label,
                        fontSize = 17.sp, modifier = Modifier.testTag("screenTitle"))
                },
                navigationIcon = {
                    if (moreView != null) TextButton(onClick = { moreView = null }) {
                        Text("‹", fontSize = 20.sp, color = Tok.txtSecondary) }
                })
        },
        bottomBar = {
            NavigationBar(containerColor = Tok.surface1) {
                Tab.entries.forEach { t ->
                    NavigationBarItem(
                        selected = tab == t && moreView == null,
                        onClick = { tab = t; moreView = null },
                        label = { Text(t.label, fontSize = 11.sp) },
                        icon = { Text(when (t) {
                            Tab.BOARD -> "▤"; Tab.NEEDS -> "!"; Tab.DASH -> "◷"; Tab.MORE -> "⋯" },
                            fontSize = 16.sp) },
                        modifier = Modifier.testTag("tab_${t.name}"),
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = Tok.accent, selectedTextColor = Tok.accent,
                            unselectedIconColor = Tok.txtTertiary, unselectedTextColor = Tok.txtTertiary,
                            indicatorColor = Tok.surface2)
                    )
                }
            }
        }
    ) { pad ->
        Box(Modifier.fillMaxSize().padding(pad)) {
            if (!DaemonClient.configured()) {
                SettingsScreen(toast) { reload++ }
            } else when {
                moreView == "sessions"  -> SessionsScreen(toast) { reload++ }
                moreView == "processes" -> ProcessesScreen(toast)
                moreView == "recordings"-> RecordingsScreen(toast)
                moreView == "users"     -> UsersScreen(toast)
                moreView == "connectors"-> ConnectorsScreen(toast)
                moreView == "workspace" -> WorkspaceHistoryScreen(toast)
                moreView == "debt"      -> DebtScreen(toast)
                moreView == "automation"-> AutomationScreen(toast)
                moreView == "import"    -> ImportScreen(toast) { reload++ }
                moreView == "history"   -> HistoryScreen()
                moreView == "chat"      -> ChatScreen(toast)
                moreView == "settings"  -> SettingsScreen(toast) { reload++ }
                tab == Tab.BOARD -> BoardScreen(tracks, metrics, laneLabels, null,
                    onOpen = { open = it }, onNew = { showNew = true },
                    onChat = { chatOpen = true })
                tab == Tab.NEEDS -> BoardScreen(tracks, null, laneLabels, "needs_you",
                    onOpen = { open = it }, onNew = { showNew = true },
                    onChat = { chatOpen = true })
                tab == Tab.DASH  -> DashboardScreen(toast)
                tab == Tab.MORE  -> MoreMenu { moreView = it }
            }
            loadErr?.let {
                Text("offline: ${it.take(70)}", fontSize = 11.sp, color = Tok.danger,
                    modifier = Modifier.align(Alignment.TopEnd).padding(8.dp))
            }
            update?.let { u ->
                Surface(color = Tok.surface2, shadowElevation = 6.dp,
                    shape = androidx.compose.foundation.shape.RoundedCornerShape(10.dp),
                    modifier = Modifier.align(Alignment.BottomCenter).padding(12.dp)
                        .testTag("updateBanner")) {
                    Row(Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text(
                            updProgress?.let { "Update ${u.versionName} - ${(it * 100).toInt()}%" }
                                ?: "Update ${u.versionName} verfügbar",
                            fontSize = 12.5.sp, color = Tok.txtPrimary)
                        if (updProgress == null) {
                            TextButton(onClick = {
                                updProgress = 0f
                                scope.launch {
                                    val f = Updater.download(ctx, u) { updProgress = it }
                                    updProgress = null
                                    if (f != null) { Updater.install(ctx, f); update = null }
                                    else toast("Update-Download fehlgeschlagen")
                                }
                            }) { Text("Installieren", fontSize = 12.5.sp, color = Tok.accent) }
                            TextButton(onClick = { update = null }) {
                                Text("Später", fontSize = 12.5.sp, color = Tok.txtTertiary) }
                        }
                    }
                }
            }
        }
    }

    if (showNew) NewCardDialog(onDismiss = { showNew = false }) { repo, task, prio ->
        showNew = false
        scope.launch {
            runCatching { DaemonClient.newTrack(repo, task, priority = prio) }
                .onSuccess { toast("Card filed"); reload++ }
                .onFailure { toast(it.message ?: "could not file") }
        }
    }

    // the copilot rides above the board rather than living in a menu
    if (chatOpen) Dialog(
        onDismissRequest = { chatOpen = false },
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        Surface(Modifier.fillMaxSize(), color = Tok.canvas) {
            Column(Modifier.fillMaxSize()) {
                Row(Modifier.fillMaxWidth().background(Tok.surface1).padding(10.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text("Board copilot", fontSize = 15.sp, color = Tok.txtPrimary,
                        modifier = Modifier.weight(1f))
                    TextButton(onClick = { chatOpen = false }) {
                        Text("close", fontSize = 13.sp, color = Tok.txtSecondary) }
                }
                ChatScreen(toast)
            }
        }
    }

    toastMsg?.let {
        Box(Modifier.fillMaxSize().padding(bottom = 96.dp), contentAlignment = Alignment.BottomCenter) {
            Surface(color = Tok.surface2, shape = MaterialTheme.shapes.medium) {
                Text(it, Modifier.padding(14.dp, 10.dp), fontSize = 13.sp, color = Tok.txtPrimary)
            }
        }
    }
}

@Composable
private fun MoreMenu(go: (String) -> Unit) {
    // 11 entries never fit a phone screen - the menu must scroll
    Column(Modifier.fillMaxSize()
        .verticalScroll(androidx.compose.foundation.rememberScrollState())
        .padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf("sessions" to "Sessions - continue a Claude Code conversation",
               "processes" to "Processes - chains, steps, new definitions",
               "recordings" to "Recordings - flight-recorder runs",
               "history" to "History - the git audit trail",
               "chat" to "Board copilot - ask about the work",
               "import" to "Import - pull work in from Jira or a page",
               "connectors" to "Connectors - scheduled feeds",
               "users" to "Users - accounts, roles, device tokens",
               "workspace" to "Workspace history - restore a past config",
               "automation" to "Automation & loop - build-loop state, night-shift, policy, repos",
               "debt" to "Debt register - shortcuts we owe",
               "settings" to "Settings - pairing and connection").forEach { (key, label) ->
            Panel(Modifier.testTag("more_$key")) {
                TextButton(onClick = { go(key) }) {
                    Text(label, fontSize = 14.sp, color = Tok.txtPrimary)
                }
            }
        }
    }
}

@Composable
private fun NewCardDialog(onDismiss: () -> Unit, onCreate: (String, String, String) -> Unit) {
    var repo by remember { mutableStateOf(HubStore.lastRepo) }
    var task by remember { mutableStateOf("") }
    val prio by remember { mutableStateOf("medium") }
    var repos by remember { mutableStateOf<List<String>>(emptyList()) }
    var pickOpen by remember { mutableStateOf(false) }

    // offer the repos this workspace already knows, so nobody types a path on a phone
    LaunchedEffect(Unit) {
        repos = runCatching { DaemonClient.knownRepos() }.getOrDefault(emptyList())
        if (repo.isBlank()) repo = repos.firstOrNull().orEmpty()
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Tok.surface1,
        title = { Text("New request", fontSize = 16.sp) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(task, { task = it }, Modifier.fillMaxWidth().testTag("newTask"),
                    placeholder = { Text("What should happen?", fontSize = 13.sp) }, colors = fieldColors())
                Text("Repo", fontSize = 11.sp, color = Tok.txtTertiary)
                Box {
                    OutlinedButton(
                        onClick = { pickOpen = true },
                        modifier = Modifier.fillMaxWidth().testTag("repoPicker"),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = Tok.txtPrimary)
                    ) {
                        Text(repo.ifBlank { "default repo" }, fontSize = 12.5.sp, maxLines = 1)
                    }
                    DropdownMenu(pickOpen, { pickOpen = false }) {
                        DropdownMenuItem(text = { Text("default repo") },
                            onClick = { repo = ""; pickOpen = false })
                        repos.forEach { r ->
                            DropdownMenuItem(
                                text = { Text(r, fontSize = 12.sp, maxLines = 1) },
                                onClick = { repo = r; pickOpen = false })
                        }
                    }
                }
                OutlinedTextField(repo, { repo = it }, Modifier.fillMaxWidth(),
                    placeholder = { Text("or type a path", fontSize = 12.sp) }, colors = fieldColors())
            }
        },
        confirmButton = {
            TextButton(onClick = { HubStore.lastRepo = repo; onCreate(repo, task, prio) },
                enabled = task.isNotBlank()) { Text("File it", color = Tok.accent) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } }
    )
}
