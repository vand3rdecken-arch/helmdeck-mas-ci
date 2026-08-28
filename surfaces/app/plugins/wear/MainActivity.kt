package app.helmdeck.wear

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import app.helmdeck.wear.data.DeviceStore

/**
 * W2a's original milestone (README.md §8 row 4) was an empty screen that
 * builds and starts - that's still exactly what an unpaired watch shows
 * today, just via PairingScreen instead of a bare placeholder. 2026-08-29:
 * once DeviceStore.load() returns a Device, this shows the SAME placeholder
 * W2a always had - the actual board view (W2b's real UI, README.md §9.1
 * item 23's board-view work) still does not exist. Pairing is real;
 * reading the board afterward is not, yet.
 *
 * TransformingLazyColumn (not the older ScalingLazyColumn) because it is
 * Wear Compose's CURRENT recommended list component - Material 3,
 * crown/rotary-scrollable, no RN equivalent whatsoever
 * (developer.android.com/training/wearables/compose/lists, checked
 * 2026-08-28). A plain Column would not respond to the crown and would
 * clip content on a round screen instead of scrolling it.
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            var paired by remember { mutableStateOf(DeviceStore.load(this) != null) }
            if (paired) {
                BoardPlaceholder()
            } else {
                PairingScreen(context = this, onPaired = { paired = true })
            }
        }
    }
}

@Composable
private fun BoardPlaceholder() {
    MaterialTheme {
        val columnState = rememberTransformingLazyColumnState()
        Box(modifier = Modifier.fillMaxSize()) {
            TransformingLazyColumn(state = columnState) {
                item { Text(text = "HelmDeck", modifier = Modifier.padding(8.dp)) }
                item { Text(text = "Gekoppelt. Board folgt.", modifier = Modifier.padding(8.dp)) }
            }
        }
    }
}
