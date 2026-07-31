package app.swarmdeck.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.swarmdeck.*
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/** Dashboard - the economics the desktop shows, condensed. */
@Composable
fun DashboardScreen(toast: (String) -> Unit) {
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        runCatching { DaemonClient.dashboard() }.onSuccess { data = it }.onFailure { err = it.message }
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        err?.let { item { EmptyNote("Could not load: $it") } }
        data?.let { d ->
            val cap = d.optJSONObject("capacity") ?: JSONObject()
            val tot = d.optJSONObject("totals") ?: JSONObject()
            item {
                Panel {
                    SectionLabel("capacity")
                    KVRow("WIP", "${cap.optInt("wip")} / ${cap.optInt("wip_limit")}")
                    KVRow("Touches today", "${cap.optInt("touches_today")} / ${cap.optInt("touch_budget_day")}")
                    KVRow("Headroom", "${cap.optInt("headroom")}")
                }
            }
            item {
                Panel {
                    SectionLabel("economics")
                    KVRow("Value delivered", "€%.2f".format(tot.optDouble("value_delivered", 0.0)))
                    KVRow("AI spend", "$%.2f".format(tot.optDouble("ai_spend", 0.0)))
                    KVRow("Margin", "€%.2f".format(tot.optDouble("margin", 0.0)),
                        if (tot.optDouble("margin", 0.0) < 0) Tok.danger else Tok.ok)
                }
            }
            val sows = d.optJSONArray("sows") ?: JSONArray()
            if (sows.length() > 0) item {
                Panel {
                    SectionLabel("statements of work")
                    for (i in 0 until sows.length()) {
                        val s = sows.optJSONObject(i) ?: continue
                        Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                            Text(s.optString("name"), fontSize = 12.5.sp, color = Tok.txtPrimary,
                                modifier = Modifier.weight(1f), maxLines = 1)
                            Text("€%.0f".format(s.optDouble("billed", 0.0)), fontSize = 12.sp, color = Tok.txtSecondary)
                            Spacer(Modifier.width(8.dp))
                            Text("%.2f".format(s.optDouble("margin", 0.0)), fontSize = 12.sp,
                                color = if (s.optDouble("margin", 0.0) < 0) Tok.danger else Tok.ok)
                        }
                    }
                }
            }
            val byModel = d.optJSONObject("ai_by_model")
            if (byModel != null && byModel.length() > 0) item {
                Panel {
                    SectionLabel("ai spend by model")
                    byModel.keys().forEach { k -> KVRow(k.replace("claude-", ""), "$%.3f".format(byModel.optDouble(k))) }
                }
            }
        } ?: run { if (err == null) item { LoadingNote() } }
    }
}

/** Processes - chain definitions: read them, advance a step, define a new one. */
@Composable
fun ProcessesScreen(toast: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var procs by remember { mutableStateOf<List<Process>?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableStateOf(0) }
    var showNew by remember { mutableStateOf(false) }

    LaunchedEffect(reload) {
        runCatching { DaemonClient.processes() }.onSuccess { procs = it; err = null }
            .onFailure { err = it.message }
    }
    Box(Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp, 12.dp, 12.dp, 88.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            err?.let { item { EmptyNote("Could not load: $it") } }
            procs?.let { list ->
                if (list.isEmpty()) item { EmptyNote("No processes yet - define one with +.") }
                items(list) { p ->
                    Panel {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(p.name, fontSize = 14.sp, fontWeight = FontWeight.Medium,
                                color = Tok.txtPrimary, modifier = Modifier.weight(1f))
                            Chip(p.status, statusColor(p.status), filled = true)
                        }
                        Spacer(Modifier.height(4.dp))
                        Text("${p.steps} steps${if (p.client.isNotEmpty()) " · ${p.client}" else ""}",
                            fontSize = 12.sp, color = Tok.txtTertiary)
                        TextButton(onClick = {
                            scope.launch {
                                runCatching { DaemonClient.advanceStep(p.id) }
                                    .onSuccess { toast("Next step dispatched"); reload++ }
                                    .onFailure { toast(it.message ?: "failed") }
                            }
                        }) { Text("run the next step", fontSize = 12.sp, color = Tok.accent) }
                    }
                }
            } ?: run { if (err == null) item { LoadingNote() } }
        }
        FloatingActionButton(onClick = { showNew = true }, containerColor = Tok.accent,
            modifier = Modifier.align(Alignment.BottomEnd).padding(18.dp)) { Text("+", fontSize = 24.sp) }
    }

    if (showNew) NewProcessDialog(onDismiss = { showNew = false }) { name, client, steps ->
        showNew = false
        scope.launch {
            runCatching { DaemonClient.newProcess(name, client, steps) }
                .onSuccess { toast("Process created"); reload++ }
                .onFailure { toast(it.message ?: "failed") }
        }
    }
}

@Composable
private fun NewProcessDialog(onDismiss: () -> Unit, onCreate: (String, String, JSONArray) -> Unit) {
    var name by remember { mutableStateOf("") }
    var client by remember { mutableStateOf("") }
    var stepsText by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Tok.surface1,
        title = { Text("New process", fontSize = 16.sp) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(),
                    placeholder = { Text("name", fontSize = 13.sp) }, colors = fieldColors(), singleLine = true)
                OutlinedTextField(client, { client = it }, Modifier.fillMaxWidth(),
                    placeholder = { Text("client (optional)", fontSize = 12.sp) }, colors = fieldColors(), singleLine = true)
                OutlinedTextField(stepsText, { stepsText = it }, Modifier.fillMaxWidth(),
                    placeholder = { Text("one step per line", fontSize = 12.sp) },
                    colors = fieldColors(), maxLines = 6)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val arr = JSONArray()
                stepsText.lines().map { it.trim() }.filter { it.isNotEmpty() }
                    .forEach { arr.put(JSONObject().put("task", it).put("mode", "do")) }
                onCreate(name.trim(), client.trim(), arr)
            }, enabled = name.isNotBlank() && stepsText.isNotBlank()) {
                Text("Create", color = Tok.accent)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } }
    )
}

/** History - the git audit trail (main line plus every card branch). */
@Composable
fun HistoryScreen() {
    var rows by remember { mutableStateOf<List<Commit>?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        runCatching { DaemonClient.gitHistory() }.onSuccess { rows = it }.onFailure { err = it.message }
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)) {
        err?.let { item { EmptyNote("Could not load: $it") } }
        rows?.let { list ->
            if (list.isEmpty()) item { EmptyNote("No commits yet (set a default repo on the desktop).") }
            items(list) { c ->
                Row(Modifier.fillMaxWidth().background(Tok.surface1, RoundedCornerShape(8.dp)).padding(9.dp)) {
                    Text(c.hash.take(7), fontSize = 10.5.sp, color = Tok.accent,
                        modifier = Modifier.width(58.dp))
                    Column(Modifier.weight(1f)) {
                        Text(c.msg, fontSize = 12.5.sp, color = Tok.txtPrimary, maxLines = 3)
                        Text("${c.date} · ${c.author} · ${c.branch}", fontSize = 10.5.sp, color = Tok.txtTertiary)
                    }
                }
            }
        } ?: run { if (err == null) item { LoadingNote() } }
    }
}

/** Slash commands, mirroring the desktop composer's board shortcuts. */
private val BOARD_SLASH = listOf(
    "/status" to "what needs me right now?",
    "/costs" to "where is the AI spend going?",
    "/stuck" to "which cards are stuck and why?",
    "/plan" to "what should I do next?",
)

/** Copilot chat - talk to the board like on the desktop: markdown answers, a
 *  context meter, slash shortcuts and a stop button. */
@Composable
fun ChatScreen(toast: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var msgs by remember { mutableStateOf<List<Pair<String, String>>>(emptyList()) }
    var draft by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var ctxIn by remember { mutableStateOf(0) }
    var ctxCost by remember { mutableStateOf(0.0) }

    LaunchedEffect(Unit) {
        runCatching { DaemonClient.chatHistory() }.onSuccess { obj ->
            val arr = obj.optJSONArray("messages") ?: JSONArray()
            msgs = (0 until arr.length()).mapNotNull { i ->
                arr.optJSONObject(i)?.let { m ->
                    m.optJSONObject("usage")?.let { u ->
                        ctxIn = u.optInt("in", ctxIn); ctxCost = u.optDouble("cost", ctxCost)
                    }
                    (if (m.optString("cls") == "you") "user" else "assistant") to m.optString("text")
                }
            }
        }
    }
    Column(Modifier.fillMaxSize()) {
        LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)) {
            if (msgs.isEmpty()) item { EmptyNote("Ask the board copilot anything.") }
            items(msgs.size) { i ->
                val (role, text) = msgs[i]
                StepRow(Step("text", if (role == "user") "user" else "assistant", text,
                    null, null, true, false, false, null, emptyList()))
            }
        }
        // slash shortcuts appear as you type "/" - the same idea as the desktop
        if (draft.startsWith("/")) Column(Modifier.fillMaxWidth().background(Tok.surface2)) {
            BOARD_SLASH.filter { it.first.startsWith(draft.substringBefore(' ')) }.forEach { (cmd, hint) ->
                Row(Modifier.fillMaxWidth().clickable { draft = hint }.padding(10.dp, 6.dp)) {
                    Text(cmd, fontSize = 12.5.sp, color = Tok.accent, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.width(8.dp))
                    Text(hint, fontSize = 12.sp, color = Tok.txtTertiary, maxLines = 1)
                }
            }
        }
        Row(Modifier.fillMaxWidth().background(Tok.surface1).padding(start = 12.dp, top = 4.dp)) {
            Text("context ${ctxIn / 1000}k · $%.3f".format(ctxCost),
                fontSize = 10.5.sp, color = Tok.txtTertiary,
                modifier = Modifier.testTag("chatContextMeter"))
        }
        Row(Modifier.background(Tok.surface1).padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(draft, { draft = it }, Modifier.weight(1f),
                placeholder = { Text("Message the board…  (/ for shortcuts)", fontSize = 13.sp) },
                colors = fieldColors(), maxLines = 4)
            Spacer(Modifier.width(8.dp))
            if (busy) TextButton(onClick = {
                scope.launch {
                    runCatching { DaemonClient.cancelChat() }
                        .onSuccess { busy = false; toast("Copilot stopped") }
                        .onFailure { toast(it.message ?: "failed") }
                }
            }) { Text("stop", fontSize = 12.sp, color = Tok.danger) }
            Button(onClick = {
                val text = draft.trim(); if (text.isEmpty()) return@Button
                msgs = msgs + ("user" to text); draft = ""; busy = true
                scope.launch {
                    runCatching { DaemonClient.chat(text) }
                        .onSuccess { r ->
                            msgs = msgs + ("assistant" to r.optString("reply", ""))
                            r.optJSONObject("usage")?.let { u ->
                                ctxIn = u.optInt("in", ctxIn); ctxCost = u.optDouble("cost", ctxCost)
                            }
                        }
                        .onFailure { toast(it.message ?: "chat failed") }
                    busy = false
                }
            }, enabled = !busy && draft.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Tok.accent)) { Text("Send") }
        }
    }
}

@Composable
fun KVRow(k: String, v: String, color: androidx.compose.ui.graphics.Color = Tok.txtPrimary) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(k, fontSize = 12.5.sp, color = Tok.txtTertiary, modifier = Modifier.weight(1f))
        Text(v, fontSize = 13.sp, color = color, fontWeight = FontWeight.Medium)
    }
}

@Composable
fun LoadingNote() {
    Row(Modifier.fillMaxWidth().padding(20.dp), horizontalArrangement = Arrangement.Center) {
        CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = Tok.accent)
    }
}

/** Automation & loop - what the harness is doing on its own: the build-loop
 *  state machine (with where it currently sits), the night-shift, the policy
 *  gates, and the repos. Same data as the desktop Settings > Automation panel. */
@Composable
fun AutomationScreen(toast: (String) -> Unit) {
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        runCatching { DaemonClient.automation() }.onSuccess { data = it; err = null }
            .onFailure { err = it.message }
    }
    val d = data
    if (err != null) { EmptyNote("Could not load automation: $err"); return }
    if (d == null) { LoadingNote(); return }

    // where the build loop currently sits (first transition = current state)
    val cur = d.optJSONArray("loop_current") ?: JSONArray()
    val curState = if (cur.length() > 0) cur.optJSONObject(0)?.optString("state") ?: "" else ""
    val curAction = if (cur.length() > 0) cur.optJSONObject(0)?.optString("action") ?: "" else ""
    val ns = d.optJSONObject("nightshift") ?: JSONObject()
    val nsCfg = ns.optJSONObject("config") ?: JSONObject()
    val tonight = ns.optJSONObject("tonight") ?: JSONObject()
    val pol = d.optJSONObject("policy") ?: JSONObject()
    val repos = d.optJSONArray("repos") ?: JSONArray()

    androidx.compose.foundation.text.selection.SelectionContainer {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp, 12.dp, 12.dp, 88.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            // --- build loop -------------------------------------------------
            item {
                Panel {
                    Text("Build-Loop", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                        color = Tok.txtPrimary)
                    Spacer(Modifier.height(2.dp))
                    Text(if (curState.isNotEmpty()) "jetzt: $curState" else "Zustand unbekannt",
                        fontSize = 12.sp, color = Tok.accent, fontWeight = FontWeight.Medium)
                    if (curAction.isNotEmpty()) {
                        Spacer(Modifier.height(2.dp))
                        Text(curAction, fontSize = 12.sp, color = Tok.txtSecondary)
                    }
                    Spacer(Modifier.height(8.dp))
                    val states = d.optJSONArray("loop_states") ?: JSONArray()
                    for (i in 0 until states.length()) {
                        val st = states.optJSONObject(i) ?: continue
                        val name = st.optString("state"); val here = name == curState
                        Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                            Text(if (here) "▸ $name" else name, fontSize = 12.sp,
                                fontWeight = if (here) FontWeight.Bold else FontWeight.Medium,
                                color = if (here) Tok.accent else Tok.txtSecondary,
                                modifier = Modifier.width(88.dp))
                            Text(st.optString("desc"), fontSize = 11.5.sp, color = Tok.txtTertiary,
                                modifier = Modifier.weight(1f))
                        }
                    }
                }
            }
            // --- night shift ------------------------------------------------
            item {
                Panel {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Night-shift", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                            color = Tok.txtPrimary, modifier = Modifier.weight(1f))
                        val on = nsCfg.optBoolean("enabled", false)
                        Chip(if (on) "an" else "aus", if (on) Tok.ok else Tok.txtTertiary, filled = on)
                    }
                    Spacer(Modifier.height(6.dp))
                    KVRow("Fenster", nsCfg.optString("window").ifEmpty { "always" })
                    KVRow("Idle-Gate", "${nsCfg.optInt("idle_minutes", 20)} min")
                    KVRow("Max/Nacht", nsCfg.optInt("max_cards", 3).toString())
                    val started = tonight.optJSONArray("started")?.length() ?: 0
                    KVRow("Heute gestartet", started.toString(),
                        if (started > 0) Tok.accent else Tok.txtPrimary)
                    if (tonight.optBoolean("limit_hit", false))
                        KVRow("Usage-Limit", "erreicht - pausiert ~5h", Tok.warn)
                }
            }
            // --- policy gates ----------------------------------------------
            item {
                Panel {
                    Text("Policy", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                        color = Tok.txtPrimary)
                    Spacer(Modifier.height(6.dp))
                    KVRow("Auto-accept grün", if (pol.optBoolean("auto_accept_green", false)) "ja" else "nein")
                    KVRow("Auto-dispatch", pol.optJSONArray("auto_dispatch_modes")?.let {
                        (0 until it.length()).joinToString(", ") { i -> it.optString(i) } }?.ifEmpty { "-" } ?: "-")
                    KVRow("Chat-Admin", pol.optJSONArray("chat_admin_roles")?.let {
                        (0 until it.length()).joinToString(", ") { i -> it.optString(i) } }?.ifEmpty { "owner" } ?: "owner")
                }
            }
            // --- repos ------------------------------------------------------
            item {
                Panel {
                    Text("Repos (${repos.length()})", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                        color = Tok.txtPrimary)
                    Spacer(Modifier.height(4.dp))
                    if (repos.length() == 0) Text("keine konfiguriert", fontSize = 12.sp, color = Tok.txtTertiary)
                    for (i in 0 until repos.length())
                        Text(repos.optString(i), fontSize = 11.5.sp, color = Tok.txtSecondary,
                            modifier = Modifier.padding(vertical = 1.dp))
                }
            }
        }
    }
}
