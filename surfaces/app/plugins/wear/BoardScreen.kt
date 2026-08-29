package app.helmdeck.wear

import android.content.Context
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
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
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
 * which is where the owner decree (README.md Â§4.7 - Henry, never the
 * worker) actually applies. This screen makes no decisions.
 *
 * Deliberately built with only `item { }` calls, NOT the `items(count) { }`
 * bulk form - the latter was never confirmed to exist on
 * TransformingLazyColumnScope this session (only singular `item` was, in
 * Â§4.5's own fetch), and a for-loop of `item { }` needs no such assumption.
 */
@Composable
fun BoardScreen(context: Context, onOpenCard: (BoardCard) -> Unit, onAskHenry: () -> Unit) {
    var status by remember { mutableStateOf("Ladeâ€¦") }
    var cards by remember { mutableStateOf<List<BoardCard>>(emptyList()) }
    var yours by remember { mutableStateOf<List<BoardCard>>(emptyList()) }
    var summary by remember { mutableStateOf<BoardSummary?>(null) }
    val scope = rememberCoroutineScope()

    fun reload() {
        val device = DeviceStore.load(context)
        if (device == null) {
            status = "Nicht gekoppelt"
            return
        }
        status = "Ladeâ€¦"
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
            summary = parseBoardSummary(result.second)
            status = when {
                parsed.isFailure -> "Antwort nicht lesbar"
                cards.isEmpty() -> "Nichts wartet auf dich"
                cards.size == 1 -> "1 wartet auf dich"
                else -> "${cards.size} warten auf dich"
            }
        }
    }

    LaunchedEffect(Unit) { reload() }

    MaterialTheme {
        val columnState = rememberTransformingLazyColumnState()
        // Same reasoning as PairingScreen: ScreenScaffold computes the
        // screen-size-relative content padding and passes it in, instead of a
        // bare Box that leaves the first and last row against the bezel.
        ScreenScaffold(columnState) { contentPadding ->
            TransformingLazyColumn(
                state = columnState,
                contentPadding = contentPadding,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                item {
                    Text(
                        text = "HelmDeck",
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(8.dp),
                    )
                }
                if (status.isNotEmpty()) {
                    item {
                        Text(
                            text = status,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.padding(8.dp),
                        )
                    }
                }
                for (c in cards) {
                    item {
                        Button(onClick = { onOpenCard(c) }, modifier = Modifier.padding(4.dp)) {
                            Text(text = c.task.ifBlank { c.id })
                        }
                    }
                }
                // The numbers the daemon already sends and this screen used to
                // discard. "Nichts wartet auf dich" alone is not a board - it is
                // an all-clear with no evidence behind it. `yours` is unstarted
                // work only the owner can begin; wip is what the machine is
                // doing right now; the age says whether any of it is still true.
                // The `yours` bucket, listed rather than counted - a number tells
                // him work exists without telling him which. Lower emphasis than
                // the blocked cards above (OutlinedButton, not filled): glances.py
                // separates the two buckets so a red gate is never buried under a
                // backlog, and the visual weight has to say the same thing.
                if (yours.isNotEmpty()) {
                    item {
                        Text(
                            text = "Nur von dir startbar",
                            textAlign = TextAlign.Center,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 2.dp),
                        )
                    }
                    for (c in yours) {
                        item {
                            OutlinedButton(onClick = { onOpenCard(c) },
                                modifier = Modifier.padding(4.dp)) {
                                Text(text = c.task.ifBlank { c.id })
                            }
                        }
                    }
                }
                summary?.let { s ->
                    if (s.wipLimit > 0) {
                        item {
                            Text(
                                text = "Läuft: ${s.wip} von ${s.wipLimit}",
                                textAlign = TextAlign.Center,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 2.dp),
                            )
                        }
                    }
                    val age = freshness(s.tsEpochSec, System.currentTimeMillis() / 1000L)
                    if (age.isNotEmpty()) {
                        item {
                            Text(
                                text = "Stand: $age",
                                textAlign = TextAlign.Center,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 2.dp),
                            )
                        }
                    }
                }
                // Henry BEFORE "Aktualisieren", and never gated on there being
                // a card. Until now the only way to reach him was tapping a
                // card, so an empty board - the normal, healthy state - meant
                // "Alles klar." and no way to say anything. Talking to Henry
                // was the point of putting HelmDeck on a wrist; it must not
                // depend on something being wrong first.
                item {
                    Button(onClick = { onAskHenry() }, modifier = Modifier.padding(6.dp)) {
                        Text("Henry fragen")
                    }
                }
                // "Henry fragen" above keeps the filled accent; refreshing is
                // maintenance, so it steps back to outlined. Same reasoning as
                // HenryScreen's own three tiers.
                item {
                    OutlinedButton(onClick = { reload() }, modifier = Modifier.padding(8.dp)) {
                        Text("Aktualisieren")
                    }
                }
            }
        }
    }
}
