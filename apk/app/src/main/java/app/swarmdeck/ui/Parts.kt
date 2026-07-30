package app.swarmdeck.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.swarmdeck.Step
import app.swarmdeck.Track

/** The desktop chip, 1:1 (web globals.css .chip): a 5px rounded RECTANGLE on
 *  bg-surface-2 with a subtle border, neutral secondary text, and a small
 *  colored status dot - NOT a colored pill. `filled` keeps a tinted-emphasis
 *  variant for the few "state" chips (automation on, debt paid). */
@Composable
fun Chip(text: String, color: Color = Tok.txtTertiary, filled: Boolean = false) {
    val showDot = color != Tok.txtTertiary   // neutral chips (AI$, client) carry no dot
    Row(
        Modifier
            .background(if (filled) color.copy(alpha = .16f) else Tok.surface2, RoundedCornerShape(5.dp))
            .border(1.dp, if (filled) color.copy(alpha = .38f) else Tok.borderSubtle, RoundedCornerShape(5.dp))
            .padding(horizontal = 7.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(5.dp)
    ) {
        if (showDot) Box(Modifier.size(7.dp)
            .background(color, androidx.compose.foundation.shape.CircleShape))
        Text(text, fontSize = 11.sp, fontWeight = FontWeight.Medium,
            color = if (filled) color else Tok.txtSecondary, maxLines = 1)
    }
}

@Composable
fun Panel(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier
            .fillMaxWidth()
            .background(Tok.surface1, RoundedCornerShape(14.dp))   // crisp solid; glow sits in the gaps
            .border(1.dp, Tok.glassBorder, RoundedCornerShape(14.dp))
            .padding(14.dp),
        content = content
    )
}

@Composable
fun SectionLabel(text: String) {
    Text(text.uppercase(), fontSize = 11.sp, color = Tok.txtTertiary,
        letterSpacing = 0.08.em, modifier = Modifier.padding(bottom = 6.dp))
}
private val Double.em get() = androidx.compose.ui.unit.TextUnit(this.toFloat(), androidx.compose.ui.unit.TextUnitType.Em)

/** A board card - same information hierarchy as the desktop tile. */
@Composable
@OptIn(ExperimentalFoundationApi::class)
fun TrackCard(t: Track, onClick: () -> Unit, onLongClick: (() -> Unit)? = null) {
    Column(
        Modifier
            .fillMaxWidth()
            .then(if (onLongClick != null)
                Modifier.combinedClickable(onClick = onClick, onLongClick = onLongClick)
            else Modifier.clickable(onClick = onClick))
            // tint the whole card so a card that responded / bounced POPS out of
            // the neutral mass at a glance (fixes "all cards look the same")
            .background(when (t.status) {
                "needs_you" -> Tok.ok.copy(alpha = .10f)
                "bounced" -> Tok.danger.copy(alpha = .10f)
                else -> Tok.surface1
            }, RoundedCornerShape(12.dp))
            .border(
                width = if (t.status == "needs_you" || t.status == "bounced") 2.dp else 1.dp,
                color = when (t.status) {
                    "needs_you" -> Tok.ok.copy(alpha = .7f)
                    "bounced" -> Tok.danger.copy(alpha = .7f)
                    else -> Tok.glassBorder
                }, shape = RoundedCornerShape(12.dp))
            .padding(12.dp)
    ) {
        // unmistakable "this card is waiting for YOU" banner
        if (t.status == "needs_you" || t.status == "bounced") {
            val isNeeds = t.status == "needs_you"
            Text(if (isNeeds) "● Antwort da – tippen" else "● abgelehnt – ansehen",
                fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold,
                color = if (isNeeds) Tok.ok else Tok.danger)
            Spacer(Modifier.height(6.dp))
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Chip(executorLabel(t.mode), executorColor(t.mode), filled = true)
            Spacer(Modifier.width(6.dp))
            Text(t.branch ?: "(no git)", fontSize = 11.sp, color = Tok.txtTertiary,
                maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            if (t.turns > 0) Text("${t.turns}t", fontSize = 11.sp, color = Tok.txtTertiary)
        }
        Spacer(Modifier.height(6.dp))
        Text(t.task, fontSize = 15.sp, fontWeight = FontWeight.Medium, color = Tok.txtPrimary,
            maxLines = 3, overflow = TextOverflow.Ellipsis)
        // the card face answers the question of ITS lane: backlog = what is
        // planned, working = what just happened, review = what was delivered,
        // done = closed. One card, state-appropriate story.
        val sub = when {
            t.lane == "backlog" -> t.description?.takeIf { it.isNotBlank() }
            t.status == "running" -> null   // running gets the live indicator instead
            t.lane == "working" && !t.lastReply.isNullOrBlank() -> t.lastReply
            t.lane == "review" && !t.lastReply.isNullOrBlank() -> "Geliefert: " + t.lastReply
            t.lane == "done" -> "Abgenommen" + (t.updated?.let { " · $it" } ?: "")
            else -> null
        }
        sub?.let {
            Spacer(Modifier.height(3.dp))
            Text(it.replace('\n', ' '), fontSize = 11.5.sp, color = Tok.txtTertiary,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            if (t.status == "running") WorkingPulse()
            t.priority?.let {
                if (it != "medium")           // medium is the default = noise
                    Chip(it, when (it) { "urgent" -> Tok.danger; "high" -> Tok.warn
                        else -> Tok.txtTertiary })
            }
            t.status?.let { Chip(it.replace('_', ' '), statusColor(it)) }
            t.due?.let { if (it.isNotEmpty()) Chip("due $it") }
            if (t.aiCost > 0) Chip("AI $%.2f".format(t.aiCost))
            t.client?.let { if (it.isNotEmpty()) Chip(it) }
        }
    }
}

/** One transcript row - the phone equivalent of the desktop Transcript component. */
@Composable
fun StepRow(s: Step) {
    when (s.kind) {
        "compaction" -> Row(Modifier.fillMaxWidth().padding(vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f).height(1.dp).background(Tok.borderSubtle))
            Text("  context compacted  ", fontSize = 11.sp, color = Tok.txtTertiary)
            Box(Modifier.weight(1f).height(1.dp).background(Tok.borderSubtle))
        }
        "tool" -> ToolRow(s)
        "todos" -> Panel(Modifier.padding(vertical = 4.dp)) {
            SectionLabel("plan / to-dos")
            s.todos.forEach { (content, status) ->
                Row(Modifier.padding(vertical = 1.dp)) {
                    Text(when (status) { "completed" -> "✓ "; "in_progress" -> "… "; else -> "· " },
                        fontSize = 12.sp, color = if (status == "completed") Tok.ok else Tok.txtTertiary)
                    Text(content, fontSize = 12.5.sp,
                        color = if (status == "completed") Tok.txtTertiary else Tok.txtSecondary)
                }
            }
        }
        "thinking" -> ThinkingRow(s)
        "system" -> {   // lifecycle event woven into the feed (dispatched/gate/merge/deploy/bounce)
            val txt = s.text ?: ""
            val bad = Regex("FAIL|BOUNC|KONFLIKT|conflict", RegexOption.IGNORE_CASE).containsMatchIn(txt)
            val good = Regex("MERGED|ACCEPTED|GATE PASSED|DISPATCHED|COMMITTED|CONNECTOR|REDUNDANT",
                RegexOption.IGNORE_CASE).containsMatchIn(txt)
            val col = if (bad) Tok.danger else if (good) Tok.ok else Tok.txtTertiary
            Row(Modifier.fillMaxWidth().padding(vertical = 5.dp, horizontal = 6.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("● ", fontSize = 10.sp, color = col)
                Text(txt, fontSize = 11.5.sp, color = if (bad || good) Tok.txtSecondary else Tok.txtTertiary,
                    modifier = Modifier.weight(1f))
                s.ts?.let { Spacer(Modifier.width(6.dp)); Text(it, fontSize = 10.sp, color = Tok.txtTertiary) }
            }
        }
        else -> MessageBubble(s)
    }
}

@Composable
private fun MessageBubble(s: Step) {
    val isUser = s.role == "user"
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start) {
        Column(
            Modifier
                .widthIn(max = 320.dp)
                .background(if (isUser) Tok.accent.copy(alpha = .22f) else Tok.surface1,
                    RoundedCornerShape(12.dp))
                .border(1.dp, Tok.glassBorder, RoundedCornerShape(12.dp))
                .padding(10.dp)
        ) {
            // agents answer in markdown - render it, the phone used to show raw.
            // SelectionContainer: long-press to select/copy (was impossible).
            androidx.compose.foundation.text.selection.SelectionContainer {
                if (isUser) Text(s.text ?: "", fontSize = 13.5.sp, color = Tok.txtPrimary)
                else Markdown(s.text ?: "")
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                s.ts?.let { Text(it, fontSize = 10.sp, color = Tok.txtTertiary) }
                if (s.streaming) {
                    Spacer(Modifier.width(6.dp))
                    Text("▍", fontSize = 11.sp, color = Tok.accent)   // live cursor
                }
                Spacer(Modifier.weight(1f))
                // Paseo-style one-tap copy of the whole message (selection
                // still works for partial copies)
                val clip = androidx.compose.ui.platform.LocalClipboardManager.current
                Text("⧉", fontSize = 13.sp, color = Tok.txtTertiary,
                    modifier = Modifier.padding(start = 8.dp).clickable {
                        clip.setText(androidx.compose.ui.text.AnnotatedString(s.text ?: ""))
                    })
            }
        }
    }
}

@Composable
private fun ThinkingRow(s: Step) {
    var open by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(if (open) "▾ Thinking" else "▸ Thinking", fontSize = 12.sp, color = Tok.txtTertiary,
            modifier = Modifier.clickable { open = !open })
        if (open) Text(s.text ?: "", fontSize = 12.5.sp, color = Tok.txtSecondary,
            modifier = Modifier.padding(start = 10.dp, top = 4.dp))
    }
}

@Composable
private fun ToolRow(s: Step) {
    var open by remember { mutableStateOf(false) }
    val expandable = !s.result.isNullOrBlank()
    Column(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp)
            .background(Tok.surface2, RoundedCornerShape(10.dp))
            .border(1.dp, Tok.glassBorder, RoundedCornerShape(10.dp))
            .clickable(enabled = expandable) { open = !open }
            .padding(9.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(s.tool ?: "tool", fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                color = if (s.ok) Tok.txtSecondary else Tok.danger)
            Spacer(Modifier.width(8.dp))
            Text(s.text ?: "", fontSize = 11.5.sp, color = Tok.txtTertiary,
                maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            if (s.running) CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 2.dp, color = Tok.accent)
            else if (expandable) Text(if (open) "▾" else "▸", fontSize = 11.sp, color = Tok.txtTertiary)
        }
        if (open && expandable) {
            Spacer(Modifier.height(6.dp))
            Box(Modifier.fillMaxWidth().heightIn(max = 320.dp).horizontalScroll(rememberScrollState())) {
                Text(s.result ?: "", fontSize = 11.sp, fontFamily = FontFamily.Monospace,
                    color = Tok.txtSecondary)
            }
        }
    }
}


/** A breathing dot + label: the unmissable "an agent is working right now"
 *  signal (Paseo shows a live indicator on running sessions; a static chip
 *  reads as stale data). */
@Composable
fun WorkingPulse() {
    val t = rememberInfiniteTransition(label = "pulse")
    val a by t.animateFloat(0.35f, 1f,
        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "a")
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(8.dp).graphicsLayer { alpha = a }
            .background(Tok.ok, androidx.compose.foundation.shape.CircleShape))
        Spacer(Modifier.width(5.dp))
        Text("arbeitet", fontSize = 11.sp, color = Tok.ok,
            modifier = Modifier.graphicsLayer { alpha = a })
    }
}
