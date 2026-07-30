package app.swarmdeck.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
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
    // Board (tiles) vs List (dense rows) - the desktop's layout switch. Timeline
    // is intentionally omitted on the phone (low value on a narrow screen).
    var layout by remember { mutableStateOf("board") }
    val shown = if (filter == "needs_you") tracks.filter { it.status == "needs_you" } else tracks
    val collapsed = remember { mutableStateMapOf<String, Boolean>() }

    Box(Modifier.fillMaxSize()) {
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(12.dp, 8.dp, 12.dp, 128.dp),  // clear the stacked FABs
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
            if (filter == null) item(key = "layout") { LayoutToggle(layout) { layout = it } }
            // NEXT UP - the desktop's #nextup strip: what to grab next, surfaced
            // above the lanes even while browsing the full board (web board.tsx:145).
            if (filter == null) {
                val nextUp = shown
                    .filter { it.lane != "done" && (it.status == "needs_you" || it.status == "bounced") }
                    .sortedWith(compareBy({ prioOrd(it.priority) }, { it.due ?: "9999" }))
                if (nextUp.isNotEmpty()) item(key = "nextup") { NextUpStrip(nextUp, onOpen) }
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
                            if (layout == "list") LRow(t, onOpen = { onOpen(t) }, onLongClick = { moving = t })
                            else TrackCard(t, onClick = { onOpen(t) }, onLongClick = { moving = t }) }
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

private fun prioOrd(p: String?) = when (p) { "urgent" -> 0; "high" -> 1; "medium" -> 2; "low" -> 3; else -> 2 }

/** Board (tiles) vs List (dense rows) - mirrors the desktop layout switch. */
@Composable
private fun LayoutToggle(layout: String, onSet: (String) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        listOf("board" to "Board", "list" to "Liste").forEach { (key, label) ->
            val on = layout == key
            Box(Modifier
                .background(if (on) Tok.accent.copy(alpha = .16f) else Tok.surface2,
                    androidx.compose.foundation.shape.RoundedCornerShape(6.dp))
                .border(1.dp, if (on) Tok.accent.copy(alpha = .5f) else Tok.borderSubtle,
                    androidx.compose.foundation.shape.RoundedCornerShape(6.dp))
                .clickable { onSet(key) }
                .padding(horizontal = 12.dp, vertical = 5.dp)) {
                Text(label, fontSize = 12.sp, fontWeight = FontWeight.Medium,
                    color = if (on) Tok.accent else Tok.txtSecondary)
            }
        }
    }
}

/** One dense list row - the desktop ListView's lrow: status dot + task + a few
 *  chips on one line. Denser than a card tile for scanning long lanes. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun LRow(t: Track, onOpen: () -> Unit, onLongClick: () -> Unit) {
    Row(Modifier.fillMaxWidth()
        .combinedClickable(onClick = onOpen, onLongClick = onLongClick)
        .padding(vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(Modifier.size(7.dp).background(statusColor(t.status),
            androidx.compose.foundation.shape.CircleShape))
        Text(t.task, fontSize = 13.sp, color = Tok.txtPrimary, maxLines = 1,
            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f))
        t.priority?.let { if (it != "medium")
            Text(it, fontSize = 10.5.sp, color = when (it) { "urgent" -> Tok.danger; "high" -> Tok.warn; else -> Tok.txtTertiary }) }
        if (t.aiCost > 0) Text("$%.2f".format(t.aiCost), fontSize = 10.5.sp, color = Tok.txtTertiary)
        t.updated?.let { Text(it, fontSize = 10.5.sp, color = Tok.txtTertiary, maxLines = 1) }
    }
}

private fun nextUpWhy(t: Track) = when {
    t.status == "bounced"   -> "gate abgelehnt - fixen"
    t.status == "needs_you" -> "Agent braucht dich"
    t.mode == "human"       -> "dein Schritt im Prozess"
    t.mode == "teach"       -> "einmal vormachen"
    t.mode == "cowork"      -> "cowork - zusammen starten"
    else                    -> "als Nächstes dran"
}

/** The board's "next up" strip - a warn-tinted band of the most actionable
 *  cards (needs-you / bounced), first four, tap to open. Mirrors web #nextup. */
@Composable
private fun NextUpStrip(items: List<Track>, onOpen: (Track) -> Unit) {
    Column(
        Modifier.fillMaxWidth()
            .background(Tok.warn.copy(alpha = .07f), androidx.compose.foundation.shape.RoundedCornerShape(12.dp))
            .border(1.dp, Tok.warn.copy(alpha = .40f), androidx.compose.foundation.shape.RoundedCornerShape(12.dp))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Text("▸ NEXT UP", fontSize = 11.5.sp, fontWeight = FontWeight.Bold, color = Tok.warn)
        items.take(4).forEach { t ->
            Row(Modifier.fillMaxWidth().clickable { onOpen(t) },
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.size(7.dp).background(statusColor(t.status),
                    androidx.compose.foundation.shape.CircleShape))
                Text(t.task, fontSize = 12.5.sp, color = Tok.txtPrimary,
                    maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f))
                Text(nextUpWhy(t), fontSize = 10.5.sp, fontWeight = FontWeight.SemiBold,
                    color = Tok.warn, maxLines = 1)
            }
        }
        if (items.size > 4)
            Text("+${items.size - 4} weitere", fontSize = 11.sp, color = Tok.txtTertiary)
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
