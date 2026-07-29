package app.swarmdeck.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.swarmdeck.*
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * The card surface - everything the desktop peek panel can do, arranged for a
 * phone: transcript first (that is what you read on the go), the editable
 * properties behind a "details" fold, destructive actions behind a menu.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CardScreen(
    track: Track,
    onBack: () -> Unit,
    onChanged: () -> Unit,
    toast: (String) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var t by remember(track.id) { mutableStateOf(track) }
    var steps by remember(track.id) { mutableStateOf<List<Step>>(emptyList()) }
    var draft by remember(track.id) { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    // optimistic echo (desktop/Paseo behavior): the sent message shows
    // IMMEDIATELY; it is dropped once the real transcript contains it
    var echo by remember { mutableStateOf<String?>(null) }
    var showMenu by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf<Pair<String, suspend () -> Unit>?>(null) }
    // A card opens on its OVERVIEW (what is this, where does it stand) - the
    // chat is a tab you choose, because long transcripts buried the description.
    var cardTab by remember(track.id) { mutableStateOf(0) }   // 0 = overview, 1 = chat
    var model by remember { mutableStateOf("auto") }
    var thinking by remember { mutableStateOf("off") }
    var models by remember { mutableStateOf<List<String>>(emptyList()) }

    LaunchedEffect(Unit) {
        runCatching {
            val a = DaemonClient.models()
            (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.optString("id") }
                .filter { it.isNotBlank() }
        }.onSuccess { models = it }
    }
    val listState = rememberLazyListState()

    // poll the transcript so a running turn streams in, like the desktop SSE feed
    LaunchedEffect(track.id) {
        while (true) {
            // follow the newest message ONLY if the reader is already at the bottom -
            // otherwise scrolling up to read gets yanked back down every poll
            val wasAtBottom = listState.layoutInfo.visibleItemsInfo.lastOrNull()
                ?.let { it.index >= steps.size - 1 } ?: true
            try {
                var fresh = DaemonClient.transcript(t.id)
                echo?.let { e ->
                    if (fresh.any { it.role == "user" && it.text?.trim() == e.trim() }) echo = null
                    else fresh = fresh + app.swarmdeck.Step(kind = "text", role = "user",
                        text = e, tool = null, result = null, ok = true,
                        running = false, streaming = false, ts = null, todos = emptyList())
                }
                // weave in the actionlog's lifecycle events (dispatched / gate / merge /
                // deploy / bounce) so the phone feed reads like the desktop's unified one
                val notes = runCatching { DaemonClient.history(t.id) }.getOrDefault(emptyList())
                    .filter { it.kind == "note" && it.detail.isNotBlank() }
                    .map { app.swarmdeck.Step(kind = "system", role = null, text = it.detail,
                        tool = null, result = null, ok = true, running = false, streaming = false,
                        ts = it.ts.ifEmpty { null }, todos = emptyList()) }
                steps = mergeFeed(fresh, notes)
                t = DaemonClient.tracks().firstOrNull { it.id == t.id } ?: t
            } catch (_: Exception) { }
            // pin-to-newest only while the chat tab is showing AND the reader was
            // already at the bottom - so reading up is never yanked back down
            if (cardTab == 1 && steps.isNotEmpty() && wasAtBottom)
                listState.animateScrollToItem(steps.size - 1)
            delay(if (t.status == "running") 1500 else 5000)
        }
    }

    Scaffold(
        containerColor = Tok.canvas,
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Tok.surface1, titleContentColor = Tok.txtPrimary),
                navigationIcon = { TextButton(onClick = onBack) { Text("‹ Back", color = Tok.txtSecondary) } },
                title = { Text(t.task, fontSize = 15.sp, maxLines = 1) },
                actions = {
                    TextButton(onClick = { showMenu = true }) { Text("⋯", fontSize = 20.sp, color = Tok.txtSecondary) }
                    DropdownMenu(showMenu, { showMenu = false }) {
                        listOf("backlog", "working", "review", "done").forEach { lane ->
                            DropdownMenuItem(
                                text = { Text("Move to $lane") },
                                enabled = lane != t.lane,
                                onClick = {
                                    showMenu = false
                                    scope.launch {
                                        runCatching { DaemonClient.moveLane(t.id, lane) }
                                            .onSuccess { res ->
                                                // Review == Abnahme: the finish may bounce (gate/merge)
                                                // and stay on Review - show WHY, don't fake "Moved".
                                                val landed = res.optString("lane", lane)
                                                val msg = when {
                                                    res.optBoolean("gate_failed") -> "Gate offen - bleibt auf Review: " +
                                                        (res.optJSONArray("gate_report")?.optString(0)?.substringBefore("\n") ?: "")
                                                    res.optBoolean("merge_failed") -> "Kann nicht landen - bleibt auf Review: " +
                                                        res.optString("merge_report").substringBefore("\n")
                                                    landed == "done" -> "Fertig → nach main gemergt"
                                                    else -> "Verschoben nach $landed"
                                                }
                                                toast(msg); onChanged()
                                            }
                                            .onFailure { toast(it.message ?: "failed") }
                                    }
                                })
                        }
                        HorizontalDivider()
                        if (t.status == "running") DropdownMenuItem(text = { Text("Stop the turn") }, onClick = {
                            showMenu = false
                            scope.launch { runCatching { DaemonClient.cancel(t.id) }
                                .onSuccess { toast("Turn cancelled") }.onFailure { toast(it.message ?: "failed") } }
                        })
                        DropdownMenuItem(text = { Text("Fork this card") }, onClick = {
                            showMenu = false
                            scope.launch { runCatching { DaemonClient.fork(t.id) }
                                .onSuccess { toast("Forked"); onChanged() }.onFailure { toast(it.message ?: "failed") } }
                        })
                        DropdownMenuItem(text = { Text("Archive") }, onClick = {
                            showMenu = false
                            confirm = "Archive this card?" to { DaemonClient.archive(t.id); onChanged(); onBack() }
                        })
                        DropdownMenuItem(
                            text = { Text("Delete", color = Tok.danger) },
                            onClick = {
                                showMenu = false
                                confirm = "Delete this card permanently?" to { DaemonClient.delete(t.id); onChanged(); onBack() }
                            })
                    }
                })
        },
        bottomBar = {
            if (cardTab == 1) Column(Modifier.background(Tok.surface1).padding(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = draft, onValueChange = { draft = it },
                        placeholder = { Text("Tell this worker what to do…", fontSize = 13.sp) },
                        modifier = Modifier.weight(1f), maxLines = 4,
                        colors = fieldColors()
                    )
                    Spacer(Modifier.width(8.dp))
                    Button(
                        onClick = {
                            val text = draft.trim(); if (text.isEmpty()) return@Button
                            sending = true; echo = text; draft = ""
                            scope.launch {
                                runCatching { DaemonClient.steer(t.id, text,
                                    model = model.takeIf { it != "auto" },
                                    thinking = thinking.takeIf { it != "off" }) }
                                    .onFailure { toast(it.message ?: "send failed"); draft = text }
                                sending = false; onChanged()
                            }
                        },
                        enabled = !sending && draft.isNotBlank(),
                        colors = ButtonDefaults.buttonColors(containerColor = Tok.accent)
                    ) { if (sending) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = androidx.compose.ui.graphics.Color.White) else Text("Send") }
                }
                // model + thinking, the same choices the desktop composer offers
                Row(verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    SmallPicker("model", model, listOf("auto") + models) { model = it }
                    SmallPicker("thinking", thinking, listOf("off", "think", "think-hard", "ultrathink")) { thinking = it }
                    if (t.status == "running") Text("running…", fontSize = 11.sp, color = Tok.accent)
                }
            }
        }
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            TabRow(
                selectedTabIndex = cardTab,
                containerColor = Tok.surface1, contentColor = Tok.accent
            ) {
                Tab(selected = cardTab == 0, onClick = { cardTab = 0 },
                    modifier = Modifier.testTag("cardTab_overview"),
                    text = { Text("Overview", fontSize = 13.sp,
                        color = if (cardTab == 0) Tok.accent else Tok.txtTertiary) })
                Tab(selected = cardTab == 1, onClick = { cardTab = 1 },
                    modifier = Modifier.testTag("cardTab_chat"),
                    text = { Text("Chat" + if (t.turns > 0) " (${t.turns}t)" else "", fontSize = 13.sp,
                        color = if (cardTab == 1) Tok.accent else Tok.txtTertiary) })
            }

            if (cardTab == 0) LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        t.status?.let { Chip(it.replace('_', ' '), statusColor(it), filled = true) }
                        Chip(t.lane, laneColor(t.lane))
                        if (t.aiCost > 0) Chip("AI $%.2f".format(t.aiCost))
                    }
                }
                item {
                    Panel(Modifier.testTag("cardDescription")) {
                        SectionLabel("description")
                        SelectionContainer {   // long-press to select + copy
                            Text(t.description?.ifBlank { null } ?: t.task,
                                fontSize = 14.sp, color = Tok.txtPrimary)
                        }
                    }
                }
                // the newest agent reply as a digest, so you know where things
                // stand without wading into the transcript
                val lastReply = steps.lastOrNull { it.kind == "text" && it.role != "user" }?.text
                    ?: t.lastReply
                if (!lastReply.isNullOrBlank()) item {
                    Panel {
                        SectionLabel("latest from the worker")
                        SelectionContainer {
                            Text(lastReply, fontSize = 13.sp, color = Tok.txtSecondary, maxLines = 12)
                        }
                        TextButton(onClick = { cardTab = 1 }) {
                            Text("open the chat ›", fontSize = 12.sp, color = Tok.accent)
                        }
                    }
                }
                item { Attachments(t.id, toast) }
                item { CardDetails(t, toast) { patch ->
                    scope.launch {
                        runCatching { DaemonClient.update(t.id, patch) }
                            .onSuccess { toast("Saved"); onChanged()
                                t = DaemonClient.tracks().firstOrNull { it.id == t.id } ?: t }
                            .onFailure { toast(it.message ?: "save failed") }
                    }
                } }
            }
            else LazyColumn(
                Modifier.fillMaxSize(), state = listState,
                contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)
            ) {
                if (steps.isEmpty()) item { EmptyNote("No transcript yet - send the first instruction below.") }
                items(steps.size) { i -> StepRow(steps[i]) }
            }
        }
    }

    confirm?.let { (msg, action) ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text("Confirm") }, text = { Text(msg) },
            confirmButton = {
                TextButton(onClick = {
                    confirm = null
                    scope.launch { runCatching { action() }.onFailure { toast(it.message ?: "failed") } }
                }) { Text("Yes", color = Tok.danger) }
            },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel") } },
            containerColor = Tok.surface1
        )
    }
}

/** Interleave the agent transcript with the actionlog's lifecycle events by
 *  timestamp - the phone's version of the desktop's unified card feed. steer/reply
 *  already live in the transcript, so only 'note' rows are injected. */
private fun mergeFeed(trans: List<app.swarmdeck.Step>, notes: List<app.swarmdeck.Step>): List<app.swarmdeck.Step> {
    if (trans.isEmpty() || notes.isEmpty()) return trans
    var last = ""
    val T = ArrayList<Pair<app.swarmdeck.Step, String>>(trans.size)
    for (s in trans) { s.ts?.let { last = it }; T.add(s to (s.ts ?: last)) }
    val out = ArrayList<app.swarmdeck.Step>(trans.size + notes.size)
    var i = 0; var j = 0
    while (i < T.size && j < notes.size) {
        val nt = notes[j].ts ?: ""
        if (nt.isNotEmpty() && nt < T[i].second) { out.add(notes[j]); j++ }
        else { out.add(T[i].first); i++ }
    }
    while (i < T.size) { out.add(T[i].first); i++ }
    while (j < notes.size) { out.add(notes[j]); j++ }
    return out
}

/**
 * Files filed with the card. Picking one goes through the system document
 * picker and is uploaded base64-encoded, so it travels the same encrypted relay
 * as everything else.
 */
@Composable
private fun Attachments(trackId: String, toast: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    val ctx = androidx.compose.ui.platform.LocalContext.current
    var files by remember(trackId) { mutableStateOf<List<Pair<String, Long>>>(emptyList()) }
    var reload by remember(trackId) { mutableStateOf(0) }
    var busy by remember { mutableStateOf(false) }

    LaunchedEffect(trackId, reload) {
        runCatching {
            val a = DaemonClient.attachments(trackId)
            (0 until a.length()).mapNotNull { i ->
                a.optJSONObject(i)?.let { it.optString("name") to it.optLong("size") }
            }
        }.onSuccess { files = it }
    }

    val picker = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.GetContent()
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        busy = true
        scope.launch {
            runCatching {
                val cr = ctx.contentResolver
                val bytes = cr.openInputStream(uri)?.use { it.readBytes() }
                    ?: error("could not read the file")
                var name = "attachment"
                cr.query(uri, null, null, null, null)?.use { c ->
                    val idx = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                    if (idx >= 0 && c.moveToFirst()) name = c.getString(idx)
                }
                DaemonClient.attach(trackId, name, cr.getType(uri) ?: "application/octet-stream", bytes)
            }.onSuccess { toast("Attached"); reload++ }
                .onFailure { toast(it.message ?: "attach failed") }
            busy = false
        }
    }

    Panel {
        SectionLabel("attachments")
        if (files.isEmpty()) Text("none yet", fontSize = 12.sp, color = Tok.txtTertiary)
        files.forEach { (name, size) ->
            Row(Modifier.fillMaxWidth().padding(vertical = 2.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text(name, fontSize = 12.5.sp, color = Tok.txtSecondary,
                    modifier = Modifier.weight(1f), maxLines = 1)
                Text("${size / 1024}k", fontSize = 11.sp, color = Tok.txtTertiary)
                TextButton(onClick = {
                    scope.launch {
                        runCatching { DaemonClient.removeAttachment(trackId, name) }
                            .onSuccess { toast("Detached"); reload++ }
                            .onFailure { toast(it.message ?: "failed") }
                    }
                }) { Text("×", fontSize = 15.sp, color = Tok.danger) }
            }
        }
        Spacer(Modifier.height(4.dp))
        OutlinedButton(onClick = { picker.launch("*/*") }, enabled = !busy,
            modifier = Modifier.testTag("attachButton"),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = Tok.txtPrimary)) {
            Text(if (busy) "attaching…" else "Attach a file", fontSize = 12.5.sp)
        }
    }
}

/** Every field the desktop lets you edit, plus rewind checkpoints. */
@Composable
private fun CardDetails(t: Track, toast: (String) -> Unit, save: (JSONObject) -> Unit) {
    val scope = rememberCoroutineScope()
    var task by remember(t.id) { mutableStateOf(t.task) }
    var desc by remember(t.id) { mutableStateOf(t.description ?: "") }
    var client by remember(t.id) { mutableStateOf(t.client ?: "") }
    var due by remember(t.id) { mutableStateOf(t.due ?: "") }
    var rate by remember(t.id) { mutableStateOf(t.rate?.toString() ?: "") }
    var priority by remember(t.id) { mutableStateOf(t.priority ?: "medium") }
    var billing by remember(t.id) { mutableStateOf(t.billing ?: "fixed") }
    var checkpoints by remember(t.id) { mutableStateOf<List<Checkpoint>>(emptyList()) }

    LaunchedEffect(t.id) { checkpoints = runCatching { DaemonClient.checkpoints(t.id) }.getOrDefault(emptyList()) }

    Panel {
        SectionLabel("card")
        Field("Title", task, { task = it }) { save(JSONObject().put("task", task)) }
        Field("Description", desc, { desc = it }, lines = 4) { save(JSONObject().put("description", desc)) }
        Picker("Priority", priority, listOf("low", "medium", "high", "urgent")) {
            priority = it; save(JSONObject().put("priority", it))
        }
        Picker("Billing", billing, listOf("fixed", "tm", "none")) {
            billing = it; save(JSONObject().put("billing", it))
        }
        if (billing == "tm") Field("Rate / h", rate, { rate = it }, numeric = true) {
            save(JSONObject().put("rate", rate.toDoubleOrNull() ?: 0.0))
        }
        Field("Client", client, { client = it }) { save(JSONObject().put("client", client)) }
        Field("Due (yyyy-mm-dd)", due, { due = it }) { save(JSONObject().put("due", due)) }

        Spacer(Modifier.height(10.dp))
        SectionLabel("technical")
        KV("Repo", t.repo ?: "-"); KV("Branch", t.branch ?: "-")
        KV("Driver", t.driver ?: "-"); KV("Session", t.sessionId?.take(12) ?: "not started")
        KV("AI cost", "$%.4f".format(t.aiCost)); KV("Turns", "${t.turns}")

        if (checkpoints.isNotEmpty()) {
            Spacer(Modifier.height(10.dp))
            SectionLabel("rewind (files only, reversible)")
            checkpoints.reversed().forEach { c ->
                Row(Modifier.fillMaxWidth().padding(vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text("turn ${c.turn} · ${c.ts.takeLast(8).take(5)}", fontSize = 11.sp,
                        color = Tok.txtTertiary, modifier = Modifier.width(96.dp))
                    Text(c.reply, fontSize = 11.sp, color = Tok.txtSecondary, maxLines = 1,
                        modifier = Modifier.weight(1f))
                    TextButton(onClick = {
                        scope.launch {
                            runCatching { DaemonClient.rewind(t.id, c.commit) }
                                .onSuccess { toast("Files restored") }
                                .onFailure { toast(it.message ?: "rewind failed") }
                        }
                    }) { Text("restore", fontSize = 11.sp, color = Tok.accent) }
                }
            }
        }
    }
}

@Composable
private fun Field(label: String, value: String, onChange: (String) -> Unit,
                  lines: Int = 1, numeric: Boolean = false, onCommit: () -> Unit) {
    Column(Modifier.padding(vertical = 3.dp)) {
        Text(label, fontSize = 11.sp, color = Tok.txtTertiary)
        OutlinedTextField(
            value = value, onValueChange = onChange,
            modifier = Modifier.fillMaxWidth(), maxLines = lines,
            textStyle = androidx.compose.ui.text.TextStyle(fontSize = 13.sp, color = Tok.txtPrimary),
            keyboardOptions = if (numeric) KeyboardOptions(keyboardType = KeyboardType.Number) else KeyboardOptions.Default,
            colors = fieldColors(),
            trailingIcon = { TextButton(onClick = onCommit) { Text("save", fontSize = 11.sp, color = Tok.accent) } }
        )
    }
}

@Composable
private fun Picker(label: String, value: String, options: List<String>, onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Column(Modifier.padding(vertical = 3.dp)) {
        Text(label, fontSize = 11.sp, color = Tok.txtTertiary)
        Box {
            OutlinedButton(onClick = { open = true },
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Tok.txtPrimary)) {
                Text(value, fontSize = 13.sp)
            }
            DropdownMenu(open, { open = false }) {
                options.forEach { o ->
                    DropdownMenuItem(text = { Text(o) }, onClick = { open = false; onPick(o) })
                }
            }
        }
    }
}

@Composable
private fun KV(k: String, v: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 1.dp)) {
        Text(k, fontSize = 11.5.sp, color = Tok.txtTertiary, modifier = Modifier.width(84.dp))
        Text(v, fontSize = 11.5.sp, color = Tok.txtSecondary)
    }
}

@Composable
private fun SmallPicker(label: String, value: String, options: List<String>, onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        TextButton(onClick = { open = true }) {
            Text("$label: ${value.removePrefix("claude-")}", fontSize = 11.sp, color = Tok.txtTertiary)
        }
        DropdownMenu(open, { open = false }) {
            options.forEach { o ->
                DropdownMenuItem(text = { Text(o.removePrefix("claude-"), fontSize = 12.sp) },
                    onClick = { open = false; onPick(o) })
            }
        }
    }
}

@Composable
fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedTextColor = Tok.txtPrimary, unfocusedTextColor = Tok.txtPrimary,
    focusedBorderColor = Tok.accent, unfocusedBorderColor = Tok.borderSubtle,
    cursorColor = Tok.accent,
    focusedContainerColor = Tok.surface2, unfocusedContainerColor = Tok.surface2,
)
