package app.swarmdeck.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.swarmdeck.DaemonClient
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/** Small helper: load a JSON array once, render it, surface failures honestly. */
@Composable
private fun <T> Loader(
    load: suspend () -> T,
    reloadKey: Int = 0,
    content: @Composable (T) -> Unit,
) {
    var data by remember(reloadKey) { mutableStateOf<T?>(null) }
    var err by remember(reloadKey) { mutableStateOf<String?>(null) }
    LaunchedEffect(reloadKey) {
        runCatching { load() }.onSuccess { data = it }.onFailure { err = it.message }
    }
    when {
        err != null -> EmptyNote("Could not load: $err")
        data == null -> LoadingNote()
        else -> content(data!!)
    }
}

/** Recordings - the flight recorder runs the desktop lists under "Recordings". */
@Composable
fun RecordingsScreen(toast: (String) -> Unit) {
    var reload by remember { mutableStateOf(0) }
    var openRun by remember { mutableStateOf<String?>(null) }

    openRun?.let { id ->
        Column(Modifier.fillMaxSize()) {
            TextButton(onClick = { openRun = null }) { Text("‹ back to recordings", color = Tok.txtSecondary) }
            Loader({ DaemonClient.runTimeline(id) }) { arr ->
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    if (arr.length() == 0) item { EmptyNote("This run has no timeline entries.") }
                    items(arr.length()) { i ->
                        val e = arr.optJSONObject(i) ?: JSONObject()
                        Row(Modifier.fillMaxWidth().background(Tok.surface1, RoundedCornerShape(8.dp)).padding(9.dp)) {
                            Text(e.optString("ts").takeLast(8), fontSize = 10.5.sp,
                                color = Tok.txtTertiary, modifier = Modifier.width(58.dp))
                            Column(Modifier.weight(1f)) {
                                Text(e.optString("kind"), fontSize = 11.5.sp, color = Tok.accent)
                                Text(e.optString("detail"), fontSize = 12.sp, color = Tok.txtSecondary, maxLines = 4)
                            }
                        }
                    }
                }
            }
        }
        return
    }

    Loader({ DaemonClient.runs() }, reload) { arr ->
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (arr.length() == 0) item {
                EmptyNote("No recordings yet. Cards on a screen-recording driver produce them.")
            }
            items(arr.length()) { i ->
                val r = arr.optJSONObject(i) ?: JSONObject()
                Panel {
                    Text(r.optString("title").ifBlank { r.optString("id") },
                        fontSize = 14.sp, fontWeight = FontWeight.Medium, color = Tok.txtPrimary)
                    Text(r.optString("started").ifBlank { r.optString("ts") },
                        fontSize = 11.sp, color = Tok.txtTertiary)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        TextButton(onClick = { openRun = r.optString("id") }) {
                            Text("timeline", fontSize = 12.sp, color = Tok.accent)
                        }
                        VideoButton(r.optString("id"), toast)
                    }
                }
            }
        }
    }
}

/**
 * Fetch a recording over the encrypted relay and play it.
 *
 * The tunnel carries text, so the video arrives as base64 slices and is
 * assembled into a local file first - you see real progress, then it plays.
 * Already-downloaded runs play straight from phone storage.
 */
@Composable
private fun VideoButton(runId: String, toast: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var progress by remember(runId) { mutableStateOf<Float?>(null) }
    var file by remember(runId) { mutableStateOf<java.io.File?>(null) }
    var playing by remember(runId) { mutableStateOf(false) }

    LaunchedEffect(runId) {
        // a previous download is reusable - no need to pull it twice
        listOf("mp4", "webm").forEach { ext ->
            val f = app.swarmdeck.HubStore.recordingFile(runId, "video.mobile.$ext")
            if (f.exists() && f.length() > 0) file = f
        }
    }

    when {
        progress != null -> Text("%.0f%%".format((progress ?: 0f) * 100),
            fontSize = 12.sp, color = Tok.txtTertiary,
            modifier = Modifier.testTag("videoProgress_$runId"))
        file != null -> TextButton(onClick = { playing = true },
            modifier = Modifier.testTag("videoPlay_$runId")) {
            Text("play", fontSize = 12.sp, color = Tok.accent)
        }
        else -> TextButton(onClick = {
            progress = 0f
            scope.launch {
                runCatching { DaemonClient.downloadRecording(runId) { progress = it } }
                    .onSuccess { f ->
                        progress = null
                        if (f == null) toast("This run has no video")
                        else { file = f; playing = true }
                    }
                    .onFailure { progress = null; toast(it.message ?: "download failed") }
            }
        }, modifier = Modifier.testTag("videoGet_$runId")) {
            Text("video", fontSize = 12.sp, color = Tok.accent)
        }
    }

    if (playing) file?.let { f ->
        androidx.compose.ui.window.Dialog(
            onDismissRequest = { playing = false },
            properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)
        ) {
            Surface(Modifier.fillMaxSize(), color = androidx.compose.ui.graphics.Color.Black) {
                Column(Modifier.fillMaxSize()) {
                    Row(Modifier.fillMaxWidth().padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(runId, fontSize = 12.sp, color = Tok.txtTertiary, modifier = Modifier.weight(1f))
                        TextButton(onClick = { playing = false }) {
                            Text("close", fontSize = 13.sp, color = Tok.txtSecondary) }
                    }
                    androidx.compose.ui.viewinterop.AndroidView(
                        modifier = Modifier.fillMaxSize().testTag("videoSurface"),
                        factory = { ctx ->
                            android.widget.VideoView(ctx).apply {
                                setMediaController(android.widget.MediaController(ctx).also { it.setAnchorView(this) })
                                setVideoPath(f.absolutePath)
                                setOnPreparedListener { it.isLooping = false; start() }
                            }
                        })
                }
            }
        }
    }
}

/** Users - create, re-role, reset, device tokens. Owner only on the daemon. */
@Composable
fun UsersScreen(toast: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var reload by remember { mutableStateOf(0) }
    var newName by remember { mutableStateOf("") }
    var newPw by remember { mutableStateOf("") }
    var newRole by remember { mutableStateOf("operator") }
    var issued by remember { mutableStateOf<String?>(null) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {

        Panel {
            SectionLabel("add a user")
            OutlinedTextField(newName, { newName = it }, Modifier.fillMaxWidth().testTag("newUserName"),
                placeholder = { Text("name", fontSize = 12.sp) }, colors = fieldColors(), singleLine = true)
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(newPw, { newPw = it }, Modifier.fillMaxWidth(),
                placeholder = { Text("password (8+ chars)", fontSize = 12.sp) }, colors = fieldColors(), singleLine = true)
            Spacer(Modifier.height(6.dp))
            RolePicker(newRole) { newRole = it }
            Spacer(Modifier.height(8.dp))
            Button(onClick = {
                scope.launch {
                    runCatching { DaemonClient.createUser(newName.trim(), newPw, newRole) }
                        .onSuccess { r ->
                            if (r.has("error")) toast(r.optString("error"))
                            else { toast("User created"); newName = ""; newPw = ""; reload++ }
                        }
                        .onFailure { toast(it.message ?: "failed") }
                }
            }, enabled = newName.isNotBlank() && newPw.length >= 8,
                colors = ButtonDefaults.buttonColors(containerColor = Tok.accent)) { Text("Create") }
        }

        Loader({ DaemonClient.users() }, reload) { arr ->
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                for (i in 0 until arr.length()) {
                    val u = arr.optJSONObject(i) ?: continue
                    val name = u.optString("name")
                    Panel {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(name, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                                color = Tok.txtPrimary, modifier = Modifier.weight(1f))
                            Chip(u.optString("role"), Tok.accent)
                        }
                        val toks = u.optJSONArray("tokens") ?: JSONArray()
                        if (toks.length() > 0) {
                            Spacer(Modifier.height(6.dp))
                            SectionLabel("device tokens")
                            for (j in 0 until toks.length()) {
                                val t = toks.optJSONObject(j) ?: continue
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(t.optString("label").ifBlank { "token" }, fontSize = 12.sp,
                                        color = Tok.txtSecondary, modifier = Modifier.weight(1f), maxLines = 1)
                                    TextButton(onClick = {
                                        scope.launch {
                                            runCatching { DaemonClient.revokeToken(name, t.optString("token")) }
                                                .onSuccess { toast("Revoked"); reload++ }
                                                .onFailure { toast(it.message ?: "failed") }
                                        }
                                    }) { Text("revoke", fontSize = 11.sp, color = Tok.danger) }
                                }
                            }
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            TextButton(onClick = {
                                scope.launch {
                                    runCatching { DaemonClient.issueToken(name, "phone") }
                                        .onSuccess { r ->
                                            issued = r.optString("token"); reload++
                                        }.onFailure { toast(it.message ?: "failed") }
                                }
                            }) { Text("+ token", fontSize = 12.sp, color = Tok.accent) }
                            TextButton(onClick = {
                                scope.launch {
                                    runCatching { DaemonClient.deleteUser(name) }
                                        .onSuccess { toast("Deleted"); reload++ }
                                        .onFailure { toast(it.message ?: "failed") }
                                }
                            }) { Text("delete", fontSize = 12.sp, color = Tok.danger) }
                        }
                    }
                }
            }
        }
    }

    issued?.let { tok ->
        AlertDialog(
            onDismissRequest = { issued = null }, containerColor = Tok.surface1,
            title = { Text("Device token", fontSize = 15.sp) },
            text = {
                Column {
                    Text("Copy it now - it is not shown again.", fontSize = 12.sp, color = Tok.txtTertiary)
                    Spacer(Modifier.height(8.dp))
                    SelectionContainerText(tok)
                }
            },
            confirmButton = { TextButton(onClick = { issued = null }) { Text("Done", color = Tok.accent) } }
        )
    }
}

@Composable
private fun SelectionContainerText(s: String) {
    androidx.compose.foundation.text.selection.SelectionContainer {
        Text(s, fontSize = 12.sp, color = Tok.txtPrimary,
            fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace)
    }
}

@Composable
private fun RolePicker(value: String, onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        OutlinedButton(onClick = { open = true },
            colors = ButtonDefaults.outlinedButtonColors(contentColor = Tok.txtPrimary)) {
            Text(value, fontSize = 13.sp)
        }
        DropdownMenu(open, { open = false }) {
            listOf("owner", "operator", "client").forEach { r ->
                DropdownMenuItem(text = { Text(r) }, onClick = { open = false; onPick(r) })
            }
        }
    }
}

/** Connectors - scheduled feeds that file cards; run or roll back on demand. */
@Composable
fun ConnectorsScreen(toast: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var reload by remember { mutableStateOf(0) }
    Loader({ DaemonClient.connectors() }, reload) { arr ->
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (arr.length() == 0) item { EmptyNote("No connectors installed.") }
            items(arr.length()) { i ->
                val c = arr.optJSONObject(i) ?: JSONObject()
                val name = c.optString("name")
                Panel(Modifier.testTag("connector_$name")) {
                    Text(name, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Tok.txtPrimary)
                    Text(c.optString("description"), fontSize = 12.sp, color = Tok.txtSecondary, maxLines = 3)
                    Text("last run: " + c.optString("last_run").ifBlank { "never" },
                        fontSize = 11.sp, color = Tok.txtTertiary)
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        TextButton(onClick = {
                            scope.launch {
                                runCatching { DaemonClient.runConnector(name) }
                                    .onSuccess { toast("Connector ran"); reload++ }
                                    .onFailure { toast(it.message ?: "failed") }
                            }
                        }) { Text("run now", fontSize = 12.sp, color = Tok.accent) }
                        TextButton(onClick = {
                            scope.launch {
                                runCatching { DaemonClient.rollbackConnector(name) }
                                    .onSuccess { toast("Rolled back"); reload++ }
                                    .onFailure { toast(it.message ?: "failed") }
                            }
                        }) { Text("roll back", fontSize = 12.sp, color = Tok.danger) }
                    }
                }
            }
        }
    }
}

/** Workspace checkpoints - the reversible history of settings/connector changes. */
@Composable
fun WorkspaceHistoryScreen(toast: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var reload by remember { mutableStateOf(0) }
    var confirmId by remember { mutableStateOf<String?>(null) }

    Loader({ DaemonClient.workspaceCheckpoints() }, reload) { arr ->
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (arr.length() == 0) item { EmptyNote("No workspace checkpoints yet.") }
            items(arr.length()) { i ->
                val c = arr.optJSONObject(i) ?: JSONObject()
                Panel {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(c.optString("reason").ifBlank { "change" }, fontSize = 13.sp,
                            color = Tok.txtPrimary, modifier = Modifier.weight(1f),
                            maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(c.optString("ts").takeLast(8), fontSize = 10.5.sp, color = Tok.txtTertiary)
                    }
                    Text("by " + c.optString("actor"), fontSize = 11.sp, color = Tok.txtTertiary)
                    TextButton(onClick = { confirmId = c.optString("id") }) {
                        Text("restore this state", fontSize = 12.sp, color = Tok.accent)
                    }
                }
            }
        }
    }

    confirmId?.let { id ->
        AlertDialog(
            onDismissRequest = { confirmId = null }, containerColor = Tok.surface1,
            title = { Text("Restore workspace") },
            text = { Text("Roll settings and connectors back to this checkpoint? " +
                          "The current state is checkpointed first, so this is reversible.",
                          fontSize = 13.sp, color = Tok.txtSecondary) },
            confirmButton = {
                TextButton(onClick = {
                    confirmId = null
                    scope.launch {
                        runCatching { DaemonClient.restoreCheckpoint(id) }
                            .onSuccess { toast("Workspace restored"); reload++ }
                            .onFailure { toast(it.message ?: "failed") }
                    }
                }) { Text("Restore", color = Tok.accent) }
            },
            dismissButton = { TextButton(onClick = { confirmId = null }) { Text("Cancel") } }
        )
    }
}

/** The debt register - load-bearing shortcuts, and filing the fix card. */
@Composable
fun DebtScreen(toast: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var reload by remember { mutableStateOf(0) }
    Loader({ DaemonClient.debt() }, reload) { arr ->
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (arr.length() == 0) item { EmptyNote("No registered debt.") }
            items(arr.length()) { i ->
                val d = arr.optJSONObject(i) ?: JSONObject()
                val status = d.optString("status")
                Panel {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(d.optString("title"), fontSize = 14.sp, fontWeight = FontWeight.Medium,
                            color = Tok.txtPrimary, modifier = Modifier.weight(1f))
                        Chip(status, if (status == "paid") Tok.ok else Tok.warn, filled = true)
                    }
                    Text(d.optString("what"), fontSize = 12.sp, color = Tok.txtSecondary, maxLines = 6)
                    if (status != "paid") TextButton(onClick = {
                        scope.launch {
                            runCatching { DaemonClient.fixDebt(d.optString("id")) }
                                .onSuccess { toast("Fix card filed"); reload++ }
                                .onFailure { toast(it.message ?: "failed") }
                        }
                    }) { Text("file the fix card", fontSize = 12.sp, color = Tok.accent) }
                }
            }
        }
    }
}

/** Imports - pull work in from Jira or a web page, like the desktop data flows. */
@Composable
fun ImportScreen(toast: (String) -> Unit, onImported: () -> Unit) {
    val scope = rememberCoroutineScope()
    var jql by remember { mutableStateOf("") }
    var url by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Panel {
            SectionLabel("from jira")
            Text("Uses the Jira connection configured on the desktop.",
                fontSize = 12.sp, color = Tok.txtTertiary)
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(jql, { jql = it }, Modifier.fillMaxWidth(),
                placeholder = { Text("JQL, e.g. project = ABC AND status = \"To Do\"", fontSize = 12.sp) },
                colors = fieldColors())
            Spacer(Modifier.height(8.dp))
            Button(onClick = {
                busy = true
                scope.launch {
                    runCatching { DaemonClient.importJira(jql.trim()) }
                        .onSuccess { r ->
                            toast(if (r.has("error")) r.optString("error")
                                  else "Imported ${r.optInt("imported")} issue(s)")
                            onImported()
                        }.onFailure { toast(it.message ?: "failed") }
                    busy = false
                }
            }, enabled = !busy && jql.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Tok.accent)) { Text("Import now") }
        }
        Panel {
            SectionLabel("from a web page")
            Text("The agent derives a process from the page's content.",
                fontSize = 12.sp, color = Tok.txtTertiary)
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(url, { url = it }, Modifier.fillMaxWidth(),
                placeholder = { Text("https://…", fontSize = 12.sp) }, colors = fieldColors(), singleLine = true)
            Spacer(Modifier.height(8.dp))
            Button(onClick = {
                busy = true
                scope.launch {
                    runCatching { DaemonClient.importUrl(url.trim()) }
                        .onSuccess { r ->
                            toast(if (r.has("error")) r.optString("error") else "Imported - see Processes")
                            onImported()
                        }.onFailure { toast(it.message ?: "failed") }
                    busy = false
                }
            }, enabled = !busy && url.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Tok.accent)) { Text("Import page") }
        }
    }
}
