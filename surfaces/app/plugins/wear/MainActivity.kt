package app.helmdeck.wear

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

/**
 * W2a milestone (README.md §8 row 4): an empty Compose-for-Wear-OS screen
 * that builds and starts. Deliberately does nothing else - no /glance call,
 * no auth, no complication. Those are W2b/c/d, and W2b specifically waits on
 * the token-model decision the card doc leaves open (README.md §9 point 2):
 * writing a network call before that is answered would mean redoing the auth
 * plumbing the moment it lands.
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
            MaterialTheme {
                val columnState = rememberTransformingLazyColumnState()
                Box(modifier = Modifier.fillMaxSize()) {
                    TransformingLazyColumn(state = columnState) {
                        item { Text(text = "HelmDeck", modifier = Modifier.padding(8.dp)) }
                        item { Text(text = "Board folgt (W2b).", modifier = Modifier.padding(8.dp)) }
                    }
                }
            }
        }
    }
}
