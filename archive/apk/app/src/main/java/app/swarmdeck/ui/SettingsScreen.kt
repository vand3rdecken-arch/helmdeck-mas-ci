package app.swarmdeck.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.swarmdeck.DaemonClient
import app.swarmdeck.HubStore
import kotlinx.coroutines.launch

/**
 * Connection + workspace settings. Pairing is the important part: paste the code
 * (or link) from SwarmDeck Settings on the desktop, or just scan the QR there -
 * the app link opens this app directly.
 */
@Composable
fun SettingsScreen(toast: (String) -> Unit, onPaired: () -> Unit) {
    val scope = rememberCoroutineScope()
    var pairInput by remember { mutableStateOf("") }
    var lanUrl by remember { mutableStateOf(HubStore.daemonUrl) }
    var probe by remember { mutableStateOf<String?>(null) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {

        Panel {
            SectionLabel("connection")
            val relayed = HubStore.relayUrl.isNotEmpty() && HubStore.room.isNotEmpty()
            KVRow("Mode", if (relayed) "relay (end-to-end encrypted)" else
                if (HubStore.daemonUrl.isNotEmpty()) "direct LAN" else "not connected",
                if (relayed) Tok.ok else Tok.txtSecondary)
            if (relayed) {
                KVRow("Relay", HubStore.relayUrl)
                KVRow("Room", HubStore.room)
            }
            Spacer(Modifier.height(8.dp))
            Button(onClick = {
                probe = "checking…"
                scope.launch {
                    runCatching { DaemonClient.tracks() }
                        .onSuccess { probe = "OK - ${it.size} card(s) reachable" }
                        .onFailure { probe = "failed: ${it.message?.take(90)}" }
                }
            }, colors = ButtonDefaults.buttonColors(containerColor = Tok.accent)) { Text("Test connection") }
            probe?.let { Text(it, fontSize = 12.sp, color = Tok.txtSecondary,
                modifier = Modifier.padding(top = 6.dp)) }
        }

        Panel {
            SectionLabel("pair with a desktop")
            Text("On the desktop: Settings → Mobile app → Pair phone. Scan the QR, " +
                 "or paste the code/link here.", fontSize = 12.sp, color = Tok.txtTertiary)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(pairInput, { pairInput = it }, Modifier.fillMaxWidth(),
                placeholder = { Text("paste pairing code or link", fontSize = 12.sp) },
                colors = fieldColors(), maxLines = 3)
            Spacer(Modifier.height(8.dp))
            Button(onClick = {
                if (HubStore.applyPairingCode(pairInput)) {
                    pairInput = ""; toast("Paired - encrypted via relay"); onPaired()
                } else toast("That does not look like a pairing code")
            }, enabled = pairInput.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Tok.accent)) { Text("Pair") }
        }

        Panel {
            SectionLabel("direct lan (optional)")
            Text("Only needed when the phone is on the same network and you are not using a relay.",
                fontSize = 12.sp, color = Tok.txtTertiary)
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(lanUrl, { lanUrl = it }, Modifier.fillMaxWidth(),
                placeholder = { Text("http://192.168.1.20:8140", fontSize = 12.sp) }, colors = fieldColors())
            Spacer(Modifier.height(8.dp))
            OutlinedButton(onClick = { HubStore.daemonUrl = lanUrl; toast("Saved") },
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Tok.txtPrimary)) { Text("Save LAN address") }
        }

        Panel {
            SectionLabel("danger zone")
            OutlinedButton(onClick = {
                HubStore.relayUrl = ""; HubStore.room = ""; HubStore.daemonPub = ""
                HubStore.deviceToken = ""; toast("Unpaired - this phone can no longer reach the daemon")
                onPaired()
            }, colors = ButtonDefaults.outlinedButtonColors(contentColor = Tok.danger)) { Text("Unpair this phone") }
        }
    }
}
