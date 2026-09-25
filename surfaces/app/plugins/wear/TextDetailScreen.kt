package app.helmdeck.wear

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnScope
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.FilledTonalButton
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.ListHeaderDefaults
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.TransformationSpec
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight

/**
 * The full text of something a list only shows as a short, ellipsised entry
 * (a card's title or body, a Henry answer, a chat message, the pairing address).
 *
 * Google's shape for it, not ours: lists hold short entries
 * (`Text(maxLines, overflow = Ellipsis)`, developer.android.com/training/wearables/
 * compose/lists), and the long text gets its own `ScreenScaffold` +
 * `TransformingLazyColumn` screen with the text as ONE item. The way out is a
 * list Button, not the scaffold's `edgeButton`: "Zurück" wrapped mid-word
 * ("Zurüc / k") in the EdgeButton's narrow bottom chord at fontScale 2.0
 * (measured on the Small Round emulator). The scaffold's `contentPadding` and
 * `minimumVerticalContentPadding` leave room after the last item, so nothing
 * here computes a spacing.
 *
 * `extra` adds further list items under the text (the address editor's actions).
 */
@Composable
fun TextDetailScreen(
    title: String,
    text: String,
    onBack: () -> Unit,
    extra: TransformingLazyColumnScope.(TransformationSpec) -> Unit = {},
) {
    val columnState = rememberTransformingLazyColumnState()
    val spec = rememberTransformationSpec()
    ScreenScaffold(scrollState = columnState) { contentPadding ->
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
                ) { Text(title, maxLines = 2, overflow = TextOverflow.Ellipsis) }
            }
            item {
                Text(
                    text = text,
                    textAlign = TextAlign.Start,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            extra(spec)
            item {
                FilledTonalButton(
                    onClick = onBack,
                    modifier = Modifier
                        .fillMaxWidth()
                        .transformedHeight(this, spec)
                        .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                    transformation = SurfaceTransformation(spec),
                ) { Text("Zurück", maxLines = 1, overflow = TextOverflow.Ellipsis) }
            }
        }
    }
}
