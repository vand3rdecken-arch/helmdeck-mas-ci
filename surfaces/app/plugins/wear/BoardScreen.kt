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
fun BoardScreen(context: Context, onOpenCard: (BoardCard) -> Unit) {
    var status by remember { mutableStateOf("Lade…") }
    var cards by remember { mutableStateOf<List<BoardCard>>(emptyList()) }
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
            cards = runCatching { parseBoardCards(result.second) }.getOrDefault(emptyList())
            status = if (cards.isEmpty()) "Alles klar." else ""
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
                item {
                    Button(onClick = { reload() }, modifier = Modifier.padding(8.dp)) {
                        Text("Aktualisieren")
                    }
                }
            }
        }
    }
}
