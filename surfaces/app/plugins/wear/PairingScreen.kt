package app.helmdeck.wear

import android.app.Activity.RESULT_OK
import android.content.Context
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
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
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnItemScope
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.ListHeaderDefaults
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.lazy.TransformationSpec
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.Text
import app.helmdeck.wear.crypto.HelmDeckBox
import app.helmdeck.wear.data.DeviceStore
import app.helmdeck.wear.data.RelayClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** README.md §4.13: the address is a dedicated, always-on Cloudflare Worker
 *  (surfaces/relay/pair_worker) that proxies EXACTLY GET /relay/pair/claim -
 *  never a raw cloudflared tunnel origin, which would expose the daemon's
 *  entire HTTP surface (including /auth/login) to the open internet. Live
 *  and verified end-to-end (checked 2026-08-29, real request through the
 *  worker to the real daemon, not assumed).
 *
 *  NOT `pair.helmdeck.de`, even though that is the intended long-term
 *  hostname (§4.13): as of this commit it still CNAMEs to the OLD raw tunnel
 *  origin (the very thing this Worker exists to replace) and reassigning it
 *  needs one manual owner step (delete that CNAME in the Cloudflare
 *  dashboard - `wrangler` is scoped `zone:read`, not `zone:write`, checked,
 *  not assumed). Pointing the default there NOW would silently defeat the
 *  entire fix. `helmdeck-pair.van-d3r-decken.workers.dev` needs no such
 *  step and is safe today - swap this constant once the dashboard step is
 *  done, nothing else in this file changes. */
private const val DEFAULT_CLAIM_BASE_URL = "https://helmdeck-pair.van-d3r-decken.workers.dev"

/**
 * The device-code pairing screen (W2b groundwork, README.md §4.6/§9.1
 * item 21). Two fields because there is no camera to scan the phone's QR
 * and no keyboard to comfortably type either: the origin the daemon is
 * reachable at right now (defaults to the dedicated pairing Worker's own
 * address, see DEFAULT_CLAIM_BASE_URL above), and the six-character code the owner
 * reads off POST /relay/pair/code's response on the phone/desktop. With the
 * address pre-filled, dictating the CODE is the only step left in the
 * common case - which is the whole point: the owner explicitly rejected
 * dictating a URL as "very painful" and asked for exactly this fix.
 *
 * Both fields offer ACTION_RECOGNIZE_SPEECH dictation (the documented Wear
 * OS voice-input path, developer.android.com/training/wearables/user-input/
 * voice, checked 2026-08-28/29) alongside a plain TextField, because Wear
 * DOES have a software keyboard/handwriting input as a fallback - dictation
 * is the fast path, not the only path.
 */
@Composable
fun PairingScreen(context: Context, onPaired: () -> Unit) {
    var claimBaseUrl by remember { mutableStateOf(DEFAULT_CLAIM_BASE_URL) }
    var code by remember { mutableStateOf("") }
    var status by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var editingAddress by remember { mutableStateOf(false) }
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
            // A code is 6 characters; capped so a dictated sentence cannot make the
            // field button taller than the round screen.
            if (text != null) code = text.replace(" ", "").trim().take(8)
        }
    }

    fun speechIntent(prompt: String) = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        putExtra(RecognizerIntent.EXTRA_PROMPT, prompt)
    }

    fun submit() {
        if (claimBaseUrl.isBlank() || code.isBlank()) {
            status = "Code fehlt"
            return
        }
        busy = true
        status = "…"
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { RelayClient.claim(claimBaseUrl, code) }.getOrNull()
            }
            if (result == null) {
                busy = false
                status = "Code ungültig"
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
                status = "Nochmal versuchen"
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

    if (editingAddress) {
        // The full address is long text: it lives on its own detail screen
        // (TextDetailScreen), never in a list button.
        TextDetailScreen(
            title = "Adresse",
            text = claimBaseUrl,
            onBack = { editingAddress = false },
        ) { spec ->
            item { ActionButton(spec, "Sprechen") { urlLauncher.launch(speechIntent("Adresse")) } }
            item { ActionButton(spec, "Standard") { claimBaseUrl = DEFAULT_CLAIM_BASE_URL } }
        }
        return
    }
    MaterialTheme {
        val columnState = rememberTransformingLazyColumnState()
        // Google's Wear Compose M3 list pattern (developer.android.com/training/
        // wearables/compose/lists): ScreenScaffold hands its contentPadding to the
        // TransformingLazyColumn, every item carries transformedHeight,
        // minimumVerticalContentPadding and SurfaceTransformation of ONE
        // TransformationSpec, and text is Text(maxLines, overflow = Ellipsis).
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
                // Code first: with the address defaulted (DEFAULT_CLAIM_BASE_URL),
                // this is the only field the owner needs to touch in the
                // common case. "Koppeln" sits DIRECTLY under it.
                item {
                    Button(
                        onClick = { codeLauncher.launch(speechIntent("Code")) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                        transformation = SurfaceTransformation(spec),
                        secondaryLabel = { Text(code.ifBlank { "sprechen" }, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    ) { Text("Code", maxLines = 1, overflow = TextOverflow.Ellipsis) }
                }
                item {
                    Button(
                        onClick = ::submit, enabled = !busy,
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                        transformation = SurfaceTransformation(spec),
                    ) { Text(if (busy) "…" else "Koppeln", maxLines = 1, overflow = TextOverflow.Ellipsis) }
                }
                if (status != null) {
                    item {
                        Text(
                            text = status ?: "", textAlign = TextAlign.Center,
                            maxLines = 2, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        )
                    }
                }
                item {
                    Button(
                        onClick = { editingAddress = true },
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                        transformation = SurfaceTransformation(spec),
                        secondaryLabel = {
                            Text(
                                if (claimBaseUrl == DEFAULT_CLAIM_BASE_URL) "Standard" else "geändert",
                                maxLines = 1, overflow = TextOverflow.Ellipsis,
                            )
                        },
                    ) { Text("Adresse", maxLines = 1, overflow = TextOverflow.Ellipsis) }
                }
            }
        }
    }
}

@Composable
private fun TransformingLazyColumnItemScope.ActionButton(
    spec: TransformationSpec, label: String, onClick: () -> Unit,
) {
    Button(
        onClick = onClick,
        modifier = Modifier
            .fillMaxWidth()
            .transformedHeight(this, spec)
            .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
        transformation = SurfaceTransformation(spec),
    ) { Text(label, maxLines = 1, overflow = TextOverflow.Ellipsis) }
}
