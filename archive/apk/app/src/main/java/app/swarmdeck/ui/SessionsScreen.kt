package app.swarmdeck.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.swarmdeck.ClaudeSession
import app.swarmdeck.DaemonClient
import kotlinx.coroutines.launch

/**
 * The desktop's Sessions view: existing Claude Code conversations on the PC,
 * brought onto the board. "Continue" wraps a session in place so steering
 * resumes that exact conversation; "Fork" branches a fresh one from the same
 * repo, seeded with the original request.
 */
@Composable
fun SessionsScreen(toast: (String) -> Unit, onAdopted: () -> Unit) {
    val scope = rememberCoroutineScope()
    var all by remember { mutableStateOf<List<ClaudeSession>?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var filter by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf<String?>(null) }
    var picked by remember { mutableStateOf<ClaudeSession?>(null) }

    LaunchedEffect(Unit) {
        runCatching { DaemonClient.claudeSessions() }
            .onSuccess { all = it }.onFailure { err = it.message }
    }

    val shown = (all ?: emptyList()).filter {
        filter.isBlank() || it.project.contains(filter, true) ||
            it.first.contains(filter, true) || it.cwd.contains(filter, true)
    }

    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = filter, onValueChange = { filter = it },
            modifier = Modifier.fillMaxWidth().padding(12.dp, 8.dp).testTag("sessionFilter"),
            placeholder = { Text("filter by project, path or first message", fontSize = 12.sp) },
            colors = fieldColors(), singleLine = true,
            keyboardOptions = KeyboardOptions.Default
        )
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(12.dp, 0.dp, 12.dp, 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            err?.let { item { EmptyNote("Could not load sessions: $it") } }
            if (all == null && err == null) item { LoadingNote() }
            if (all != null && shown.isEmpty()) item {
                EmptyNote(if (filter.isBlank()) "No Claude Code sessions found on the desktop."
                          else "Nothing matches \"$filter\".")
            }
            items(shown) { s ->
                Panel(Modifier.testTag("session_${s.id.take(8)}")) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(s.project.ifBlank { "(no project)" }, fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold, color = Tok.txtPrimary,
                            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                        Text(s.lastActive.take(16), fontSize = 10.5.sp, color = Tok.txtTertiary)
                    }
                    Spacer(Modifier.height(4.dp))
                    Text(s.first.ifBlank { "(no opening message)" }, fontSize = 12.5.sp,
                        color = Tok.txtSecondary, maxLines = 3, overflow = TextOverflow.Ellipsis)
                    Spacer(Modifier.height(4.dp))
                    Text(s.cwd, fontSize = 10.5.sp, color = Tok.txtTertiary,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = { picked = s },
                            enabled = busy == null,
                            colors = ButtonDefaults.buttonColors(containerColor = Tok.accent)
                        ) { Text("Bring onto the board", fontSize = 12.5.sp) }
                        if (busy == s.id) CircularProgressIndicator(
                            Modifier.size(18.dp).align(Alignment.CenterVertically),
                            strokeWidth = 2.dp, color = Tok.accent)
                    }
                }
            }
        }
    }

    picked?.let { s ->
        AlertDialog(
            onDismissRequest = { picked = null },
            containerColor = Tok.surface1,
            title = { Text("Bring this session onto the board", fontSize = 15.sp) },
            text = {
                Column {
                    Text("Continue keeps the conversation: steering resumes this exact " +
                         "session in its own folder, no new branch.",
                        fontSize = 12.5.sp, color = Tok.txtSecondary)
                    Spacer(Modifier.height(8.dp))
                    Text("Fork starts a fresh session on a new branch and worktree, " +
                         "seeded with the original request. The source stays untouched.",
                        fontSize = 12.5.sp, color = Tok.txtSecondary)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    picked = null; busy = s.id
                    scope.launch {
                        runCatching { DaemonClient.adoptSession(s, "continue") }
                            .onSuccess { toast("Session continued as a card"); onAdopted() }
                            .onFailure { toast(it.message ?: "could not adopt") }
                        busy = null
                    }
                }) { Text("Continue", color = Tok.accent) }
            },
            dismissButton = {
                Row {
                    TextButton(onClick = {
                        picked = null; busy = s.id
                        scope.launch {
                            runCatching { DaemonClient.adoptSession(s, "fork") }
                                .onSuccess { toast("Forked onto a new branch"); onAdopted() }
                                .onFailure { toast(it.message ?: "could not fork") }
                            busy = null
                        }
                    }) { Text("Fork") }
                    TextButton(onClick = { picked = null }) { Text("Cancel") }
                }
            }
        )
    }
}
