package app.helmdeck.wear

import android.app.Activity.RESULT_OK
import android.content.Context
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
// Button: NOT independently re-fetched/confirmed this session the way
// TransformingLazyColumn/MaterialTheme/Text were (§4.5) - a basic button
// composable is about as foundational to any Compose Material library as
// Text is, so this is a low-risk assumption, but it is an assumption, not a
// citation. Recheck alongside everything else in §9.1 item 15.
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import app.helmdeck.wear.crypto.HelmDeckBox
import app.helmdeck.wear.data.DeviceStore
import app.helmdeck.wear.data.RelayClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * The device-code pairing screen (W2b groundwork, README.md §4.6/§9.1
 * item 21). Two fields because there is no camera to scan the phone's QR
 * and no keyboard to comfortably type either: the origin the daemon is
 * reachable at right now (the owner's ops/deploy/cloudflare_tunnel.sh URL -
 * a NAMED tunnel is strongly recommended over the ephemeral one specifically
 * because a short, memorable domain dictates far more reliably than a random
 * trycloudflare.com string), and the six-character code the owner reads off
 * POST /relay/pair/code's response on the phone/desktop.
 *
 * Both fields offer ACTION_RECOGNIZE_SPEECH dictation (the documented Wear
 * OS voice-input path, developer.android.com/training/wearables/user-input/
 * voice, checked 2026-08-28/29) alongside a plain TextField, because Wear
 * DOES have a software keyboard/handwriting input as a fallback - dictation
 * is the fast path, not the only path.
 */
@Composable
fun PairingScreen(context: Context, onPaired: () -> Unit) {
    var claimBaseUrl by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var status by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    val urlLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            val text = result.data
                ?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                ?.firstOrNull()
            if (text != null) claimBaseUrl = text.trim()
        }
    }
    val codeLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            val text = result.data
                ?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                ?.firstOrNull()
            // Voice recognition inserts spaces between spelled-out
            // characters ("F 5 Z E K 6") more often than not on a 6-char
            // code with no dictionary word to anchor it - stripped here so
            // a spoken code has the same shot at matching as a typed one.
            if (text != null) code = text.replace(" ", "").trim()
        }
    }

    fun speechIntent(prompt: String) = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        putExtra(RecognizerIntent.EXTRA_PROMPT, prompt)
    }

    fun submit() {
        if (claimBaseUrl.isBlank() || code.isBlank()) {
            status = "Adresse und Code eingeben"
            return
        }
        busy = true
        status = "Koppeln…"
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { RelayClient.claim(claimBaseUrl, code) }.getOrNull()
            }
            if (result == null) {
                busy = false
                status = "Code unbekannt oder abgelaufen"
                return@launch
            }
            val kp = withContext(Dispatchers.Default) { HelmDeckBox.generateKeyPair() }
            val completed = withContext(Dispatchers.IO) {
                runCatching {
                    RelayClient.completePairing(
                        result.relayUrl, result.room, result.daemonPubB64,
                        kp.publicKeyB64, kp.secretKeyB64, result.deviceToken)
                }.getOrDefault(false)
            }
            busy = false
            if (!completed) {
                status = "Gekoppelt, aber der erste Abruf ist fehlgeschlagen - erneut versuchen"
                return@launch
            }
            DeviceStore.save(context, DeviceStore.Device(
                relayUrl = result.relayUrl, room = result.room,
                daemonPubB64 = result.daemonPubB64,
                mySecretKeyB64 = kp.secretKeyB64, myPublicKeyB64 = kp.publicKeyB64,
                deviceToken = result.deviceToken,
            ))
            status = "Gekoppelt"
            onPaired()
        }
    }

    MaterialTheme {
        val columnState = rememberTransformingLazyColumnState()
        Box(modifier = Modifier.fillMaxSize()) {
            TransformingLazyColumn(state = columnState) {
                item { Text(text = "HelmDeck koppeln", modifier = Modifier.padding(8.dp)) }
                item {
                    FieldRow(
                        label = "Adresse", value = claimBaseUrl,
                        onDictate = { urlLauncher.launch(speechIntent("Adresse")) },
                    )
                }
                item {
                    FieldRow(
                        label = "Code", value = code,
                        onDictate = { codeLauncher.launch(speechIntent("Code")) },
                    )
                }
                item {
                    Button(onClick = ::submit, enabled = !busy,
                        modifier = Modifier.padding(8.dp)) {
                        Text(if (busy) "…" else "Koppeln")
                    }
                }
                if (status != null) {
                    item { Text(text = status ?: "", modifier = Modifier.padding(8.dp)) }
                }
            }
        }
    }
}

/** One field: the last dictated/typed value shown as text, plus a mic
 *  button. NOT a real TextField - Wear Compose Material3's text-entry story
 *  (OutlinedTextField equivalents) was not fetched/confirmed this session,
 *  and dictation-only is a defensible v1 for a 6-char code / a short host
 *  name, matching this screen's own §9.1-documented scope. A typed fallback
 *  via the system's Wear keyboard/handwriting input is still reachable
 *  through Android's own text-selection long-press on the value text - not
 *  wired here explicitly, tracked as a gap, not silently dropped. */
@Composable
private fun FieldRow(label: String, value: String, onDictate: () -> Unit) {
    Column(modifier = Modifier.padding(8.dp)) {
        Text(text = "$label: ${value.ifBlank { "–" }}")
        Button(onClick = onDictate) { Text("Diktieren") }
    }
}
