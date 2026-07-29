package app.swarmdeck.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.swarmdeck.DaemonClient
import app.swarmdeck.Metrics
import app.swarmdeck.Track
import kotlinx.coroutines.launch

/**
 * The board, laid out for a phone: the desktop's four columns become collapsible
 * sections in one scroll, so the same information fits a narrow screen without
 * horizontal panning.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BoardScreen(
    tracks: List<Track>,
    metrics: Metrics?,
    laneLabels: Map<String, String>,
    filter: String?,                 // null = all, or "needs_you"
    onOpen: (Track) -> Unit,
    onNew: () -> Unit,
    onChat: (() -> Unit)? = null,
) {
    val lanes = listOf("backlog", "working", "review", "done")
    // long-press a card -> move it without opening it (the phone's drag&drop)
    var moving by remember { mutableStateOf<Track?>(null) }
    val shown = if (filter == "needs_you") tracks.filter { it.status == "needs_you" } else tracks
    val collapsed = remember { mutableStateMapOf<String, Boolean>() }

    Box(Modifier.fillMaxSize()) {
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(12.dp, 8.dp, 12.dp, 88.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            metrics?.let { m ->
                item {
                    Panel {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Stat("WIP", "${m.wip}/${m.wipLimit}", Modifier.weight(1f))
                            Stat("Touches", "${m.touches}/${m.touchBudget}", Modifier.weight(1f))
                            Stat("Headroom", "${m.headroom}", Modifier.weight(1f))
                        }
                        if (m.aiCost > 0 || m.billed > 0) {
                            Spacer(Modifier.height(8.dp))
                            Row {
                                Stat("Billed", "€%.0f".format(m.billed), Modifier.weight(1f))
                                Stat("AI", "$%.2f".format(m.aiCost), Modifier.weight(1f))
                                Stat("Margin", "€%.2f".format(m.margin), Modifier.weight(1f),
                                    if (m.margin < 0) Tok.danger else Tok.ok)
                            }
                        }
                    }
                }
            }
            if (filter == "needs_you") {
                if (shown.isEmpty()) item { EmptyNote("Nothing needs you right now.") }
                items(shown, key = { it.id }) { t ->
                    TrackCard(t, onClick = { onOpen(t) }, onLongClick = { moving = t }) }
            } else {
                lanes.forEach { lane ->
                    val inLane = shown.filter { it.lane == lane }
                    item(key = "h_$lane") {
                        LaneHeader(
                            label = laneLabels[lane] ?: lane.replaceFirstChar { it.uppercase() },
                            count = inLane.size,
                            lane = lane,
                            collapsed = collapsed[lane] == true,
                            onToggle = { collapsed[lane] = !(collapsed[lane] ?: false) }
                        )
                    }
                    if (collapsed[lane] != true) {
                        if (inLane.isEmpty()) item(key = "e_$lane") { EmptyNote("empty") }
                        items(inLane, key = { it.id }) { t ->
                            TrackCard(t, onClick = { onOpen(t) }, onLongClick = { moving = t }) }
                    }
                }
            }
        }
        moving?.let { t ->
            val scope = rememberCoroutineScope()
            AlertDialog(
                onDismissRequest = { moving = null },
                containerColor = Tok.surface1, titleContentColor = Tok.txtPrimary,
                title = { Text(t.task, fontSize = 14.sp, maxLines = 2) },
                text = {
                    Column {
                        lanes.filter { it != t.lane }.forEach { lane ->
                            TextButton(onClick = {
                                moving = null
                                scope.launch {
                                    runCatching { DaemonClient.moveLane(t.id, lane) }
                                        .onFailure { e -> /* gate bounce etc. surfaces on refresh */ }
                                }
                            }, modifier = Modifier.fillMaxWidth()) {
                                Text("→ " + (laneLabels[lane] ?: lane.replaceFirstChar { c -> c.uppercase() }),
                                    fontSize = 14.sp, color = laneColor(lane))
                            }
                        }
                    }
                },
                confirmButton = {},
                dismissButton = { TextButton(onClick = { moving = null }) {
                    Text("Abbrechen", color = Tok.txtTertiary) } })
        }
        // The copilot belongs ON the board, like the desktop's floating button -
        // asking about the work should not require digging through a menu.
        Column(
            Modifier.align(Alignment.BottomEnd).padding(18.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            onChat?.let {
                SmallFloatingActionButton(
                    onClick = it,
                    containerColor = Tok.surface2, contentColor = Tok.accent,
                    modifier = Modifier.testTag("chatFab")
                ) { Text("‹›", fontSize = 15.sp) }
            }
            FloatingActionButton(
                onClick = onNew,
                containerColor = Tok.accent,
                modifier = Modifier.testTag("newCardFab")
            ) { Text("+", fontSize = 24.sp) }
        }
    }
}

@Composable
private fun LaneHeader(label: String, count: Int, lane: String, collapsed: Boolean, onToggle: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(top = 6.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(Modifier.size(8.dp).background(laneColor(lane), CircleShape))
        Spacer(Modifier.width(8.dp))
        Text(label, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Tok.txtSecondary)
        Spacer(Modifier.width(6.dp))
        Text("$count", fontSize = 12.sp, color = Tok.txtTertiary, modifier = Modifier.weight(1f))
        TextButton(onClick = onToggle) {
            Text(if (collapsed) "show" else "hide", fontSize = 12.sp, color = Tok.txtTertiary)
        }
    }
}

@Composable
private fun Stat(label: String, value: String, modifier: Modifier = Modifier, color: androidx.compose.ui.graphics.Color = Tok.txtPrimary) {
    Column(modifier) {
        Text(label, fontSize = 11.sp, color = Tok.txtTertiary)
        Text(value, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = color)
    }
}

@Composable
fun EmptyNote(text: String) {
    Text(text, fontSize = 12.sp, color = Tok.txtTertiary,
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp))
}
