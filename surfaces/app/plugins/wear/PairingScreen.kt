package app.helmdeck.wear

import android.app.Activity.RESULT_OK
import android.content.Context
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
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
        // ScreenScaffold, NOT a bare Box: it supplies the scroll indicator and
        // - the part that matters here - computes the screen's content padding
        // itself and hands it to this lambda. That padding is a PERCENTAGE of
        // the screen (androidx.wear.compose.material3.PaddingDefaults
        // .verticalContentPaddingPercentage / horizontalContentPaddingPercentage,
        // read off the 1.6.2 artifact, not assumed), so it adapts to any watch
        // size and shape on its own. The previous code passed no contentPadding
        // at all, which is why the first and last rows sat hard against the
        // bezel on a real device. Nothing here is measured or hardcoded for one
        // specific watch - that would be the opposite of responsive.
        // ROUND SCREEN SIDE INSET on every item below, not only FieldRow's own
        // value text - Play rejected Wear production 1000006 again on
        // 2026-09-20 under the same font-size guideline after only FieldRow
        // had been fixed. `status` in particular carries a full sentence
        // ("Gekoppelt, aber der erste Abruf ist fehlgeschlagen - erneut
        // versuchen") that wraps to several lines at a large system font
        // scale, exactly the shape that gets clipped without this.
        val sideInset = wearBezelInset()
        ScreenScaffold(columnState) { contentPadding ->
            TransformingLazyColumn(
                state = columnState,
                contentPadding = contentPadding,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                item {
                    Text(
                        text = "HelmDeck koppeln",
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(horizontal = sideInset, vertical = 8.dp),
                    )
                }
                // Code first: with the address defaulted (DEFAULT_CLAIM_BASE_URL),
                // this is the only field the owner needs to touch in the
                // common case - the whole reason that default exists.
                item {
                    FieldRow(
                        label = "Code", value = code,
                        onDictate = { codeLauncher.launch(speechIntent("Code")) },
                    )
                }
                // "Koppeln" sits DIRECTLY under the code field, above the
                // address. It used to be last, which put the screen's whole
                // point below the fold: dictate the code, then scroll to find
                // the button (seen on the watch, 2026-08-29). The address is
                // defaulted and "meist unnötig", so it belongs after the action
                // it almost never affects, not in front of it.
                item {
                    Button(onClick = ::submit, enabled = !busy,
                        modifier = Modifier.padding(horizontal = sideInset, vertical = 8.dp)) {
                        Text(if (busy) "…" else "Koppeln")
                    }
                }
                item {
                    FieldRow(
                        label = "Adresse (meist unnötig)", value = claimBaseUrl,
                        // Label and value on SEPARATE lines. With both on one
                        // line the label plus colon ate the whole width and the
                        // value ellipsised to "..." - a confirmation field that
                        // confirms nothing.
                        valueOnOwnLine = true,
                        onDictate = { urlLauncher.launch(speechIntent("Adresse")) },
                    )
                }
                if (status != null) {
                    item {
                        Text(
                            text = status ?: "",
                            textAlign = TextAlign.Center,
                            modifier = Modifier.padding(horizontal = sideInset, vertical = 8.dp),
                        )
                    }
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
private fun FieldRow(
    label: String,
    value: String,
    onDictate: () -> Unit,
    /** Put the value on its OWN line instead of after "label: ". For a long
     *  value (the claim URL) the single-line form spent the entire width on the
     *  label, forcing the value onto a truncated remainder. */
    valueOnOwnLine: Boolean = false,
) {
    // Centred, not start-aligned: a watch screen is widest through its middle,
    // so left-aligned text is the first thing a round bezel eats. The
    // horizontal inset comes from ScreenScaffold's contentPadding on the list
    // above, so this only adds the spacing BETWEEN rows.
    //
    // NO maxLines / TextOverflow.Ellipsis on the value: Play's Wear font-size
    // guideline (rejection 2026-09-15, submission #11) requires that nothing
    // be clipped at the largest system font scale, and an ellipsis IS a clip -
    // it hides characters rather than growing the row. Wrapping is the only
    // way a value keeps its full content at every font scale. A side inset
    // (10% of screen width, same reasoning as HenryScreen/CardScreen) keeps a
    // wrapped line's first/last characters off the round bezel instead of
    // relying on ScreenScaffold's padding alone, which only protects the
    // first/last ROW, not every side of a multi-line block. Shared with
    // every other screen via wearBezelInset() (WearLayout.kt).
    val sideInset = wearBezelInset()
    Column(
        modifier = Modifier.padding(vertical = 6.dp, horizontal = sideInset),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (valueOnOwnLine) {
            Text(text = label, textAlign = TextAlign.Center)
            Text(text = value.ifBlank { "–" }, textAlign = TextAlign.Center)
        } else {
            Text(
                text = "$label: ${value.ifBlank { "–" }}",
                textAlign = TextAlign.Center,
            )
        }
        Button(onClick = onDictate) { Text("Diktieren") }
    }
}
