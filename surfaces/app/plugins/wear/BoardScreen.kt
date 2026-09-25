package app.helmdeck.wear

import android.content.Context
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.ListHeaderDefaults
import androidx.wear.compose.material3.ListHeader
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import androidx.wear.compose.material3.ChildButton
import androidx.wear.compose.material3.OutlinedButton
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.Text
import app.helmdeck.wear.data.DeviceStore
import app.helmdeck.wear.data.RelayClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * GET /wear/board (routes_wear.py) - reuses glance_payload() UNCHANGED, the
 * same small curated "what needs you" read the glasses already get. Purely
 * a list: tapping a card hands its id/task/question over to CardScreen,
 * which is where the owner decree (README.md §4.7 - Henry, never the
 * worker) actually applies. This screen makes no decisions.
 *
 * Deliberately built with only `item { }` calls, NOT the `items(count) { }`
 * bulk form - the latter was never confirmed to exist on
 * TransformingLazyColumnScope this session (only singular `item` was, in
 * §4.5's own fetch), and a for-loop of `item { }` needs no such assumption.
 */
@Composable
fun BoardScreen(context: Context, onOpenCard: (BoardCard) -> Unit, onAskHenry: () -> Unit) {
    var status by remember { mutableStateOf("Lade…") }
    var cards by remember { mutableStateOf<List<BoardCard>>(emptyList()) }
    var yours by remember { mutableStateOf<List<BoardCard>>(emptyList()) }
    var working by remember { mutableStateOf(BoardSection(emptyList(), 0)) }
    var backlog by remember { mutableStateOf(BoardSection(emptyList(), 0)) }
    var summary by remember { mutableStateOf<BoardSummary?>(null) }
    val scope = rememberCoroutineScope()

    fun reload() {
        val device = DeviceStore.load(context)
        if (device == null) {
            status = "Nicht gekoppelt"
            return
        }
        status = "Lade…"
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    RelayClient.authedCall(
                        device.relayUrl, device.room, device.daemonPubB64,
                        device.myPublicKeyB64, device.mySecretKeyB64, device.deviceToken,
                        "GET", "/wear/board")
                }.getOrNull()
            }
            if (result == null || result.first !in 200..299) {
                status = "Konnte nicht laden"
                return@launch
            }
            // A PARSE FAILURE MUST NOT LOOK LIKE AN EMPTY BOARD. This used to be
            // `.getOrDefault(emptyList())`, so a malformed payload produced the
            // exact same "Alles klar." as a genuinely quiet board - the owner
            // would be told everything is fine while the watch had in fact
            // failed to read the answer. Same class of silent failure this repo
            // rejects everywhere else.
            val parsed = runCatching { parseBoardCards(result.second) }
            cards = parsed.getOrDefault(emptyList())
            yours = parseYours(result.second)
            val pipe = parsePipeline(result.second)
            working = pipe.first
            backlog = pipe.second
            summary = parseBoardSummary(result.second)
            status = when {
                parsed.isFailure -> "Antwort nicht lesbar"
                cards.isEmpty() -> "Nichts wartet auf dich"
                cards.size == 1 -> "1 wartet auf dich"
                else -> "${cards.size} warten auf dich"
            }
        }
    }

    // THE BOARD IS NOW LIVE, on the SAME channel as the chat (owner decision
    // 2026-09-02: "Mitnehmen"). This was `LaunchedEffect(Unit) { reload() }` -
    // load once when the screen opened, then nothing until the owner pressed
    // Reload. A card moving lane, a worker asking a question, a run finishing:
    // none of it reached the wrist while he was looking straight at the list.
    //
    // ONE effect, not two: keying on the board version covers the FIRST load
    // (the effect runs on composition whatever the value is) and every
    // subsequent change, so there is no separate initial fetch that could
    // disagree with the live one. Opening the screen before the stream has
    // answered costs one extra GET when the first version lands - the same
    // deliberate trade the chat makes, and for the same reason: a duplicate
    // read is cheap, a card silently waiting on the owner is not.
    //
    // `v` only. WearStream assigns the daemon's CURRENT versions, and writing an
    // unchanged Int to a Compose state is a no-op, so a chat-only bump never
    // reloads the board.
    LaunchedEffect(WearStream.board.value) { reload() }

    MaterialTheme {
        val columnState = rememberTransformingLazyColumnState()
        // Google's Wear list pattern (developer.android.com/training/wearables/
        // compose/lists): ScreenScaffold's contentPadding into the column, and every
        // item with transformedHeight + minimumVerticalContentPadding +
        // SurfaceTransformation of one spec. Entries are SHORT: a card title is
        // Text(maxLines = 2, overflow = Ellipsis) here and reads in full on the
        // card screen (TextDetailScreen).
        val spec = rememberTransformationSpec()
        ScreenScaffold(columnState) { contentPadding ->
            TransformingLazyColumn(
                state = columnState,
                contentPadding = contentPadding,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                item {
                    ListHeader(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .minimumVerticalContentPadding(ListHeaderDefaults.minimumTopListContentPadding),
                        transformation = SurfaceTransformation(spec),
                    ) { Text("HelmDeck", maxLines = 2, overflow = TextOverflow.Ellipsis) }
                }
                if (status.isNotEmpty()) {
                    item {
                        Text(
                            text = status, textAlign = TextAlign.Center,
                            maxLines = 2, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        )
                    }
                }
                for (c in cards) {
                    item {
                        Button(
                            onClick = { onOpenCard(c) },
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                            transformation = SurfaceTransformation(spec),
                        ) { Text(c.task.ifBlank { c.id }, maxLines = 2, overflow = TextOverflow.Ellipsis) }
                    }
                }
                // The numbers the daemon already sends: `yours` is unstarted work only
                // the owner can begin, wip is what the machine is doing right now, the
                // age says whether any of it is still true. Three emphasis tiers,
                // most to least urgent: filled (blocked), outlined (yours), hairline
                // (context) - all obviously touchable, still ranked.
                if (yours.isNotEmpty()) {
                    item {
                        Text(
                            text = "Von dir", textAlign = TextAlign.Center,
                            maxLines = 1, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        )
                    }
                    for (c in yours) {
                        item {
                            OutlinedButton(
                                onClick = { onOpenCard(c) },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                                transformation = SurfaceTransformation(spec),
                            ) { Text(c.task.ifBlank { c.id }, maxLines = 2, overflow = TextOverflow.Ellipsis) }
                        }
                    }
                }
                if (working.total > 0) {
                    item {
                        Text(
                            text = if (summary?.let { it.wipLimit > 0 } == true)
                                       "In Arbeit: ${working.total} von ${summary!!.wipLimit}"
                                   else "In Arbeit: ${working.total}",
                            textAlign = TextAlign.Center,
                            maxLines = 2, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        )
                    }
                    for (c in working.cards) {
                        item {
                            ChildButton(
                                onClick = { onOpenCard(c) },
                                border = BorderStroke(1.dp, WearTokens.borderSubtle),
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                                transformation = SurfaceTransformation(spec),
                            ) { Text(c.task.ifBlank { c.id }, maxLines = 2, overflow = TextOverflow.Ellipsis) }
                        }
                    }
                }
                if (backlog.total > 0) {
                    item {
                        Text(
                            text = "Backlog: ${backlog.total}", textAlign = TextAlign.Center,
                            maxLines = 1, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        )
                    }
                    for (c in backlog.cards) {
                        item {
                            ChildButton(
                                onClick = { onOpenCard(c) },
                                border = BorderStroke(1.dp, WearTokens.borderSubtle),
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                                transformation = SurfaceTransformation(spec),
                            ) { Text(c.task.ifBlank { c.id }, maxLines = 2, overflow = TextOverflow.Ellipsis) }
                        }
                    }
                }
                summary?.let { s ->
                    val age = freshness(s.tsEpochSec, System.currentTimeMillis() / 1000L)
                    if (age.isNotEmpty()) {
                        item {
                            Text(
                                text = "Stand: $age", textAlign = TextAlign.Center,
                                maxLines = 2, overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                            )
                        }
                    }
                }
                // Henry BEFORE the refresh, and never gated on there being a card:
                // talking to Henry is the point of putting HelmDeck on a wrist.
                item {
                    Button(
                        onClick = { onAskHenry() },
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                        transformation = SurfaceTransformation(spec),
                    ) { Text("Henry", maxLines = 2, overflow = TextOverflow.Ellipsis) }
                }
                // Refreshing is maintenance, so it steps back to outlined.
                item {
                    OutlinedButton(
                        onClick = { reload() },
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                        transformation = SurfaceTransformation(spec),
                    ) { Text("Neu laden", maxLines = 2, overflow = TextOverflow.Ellipsis) }
                }
            }
        }
    }
}
