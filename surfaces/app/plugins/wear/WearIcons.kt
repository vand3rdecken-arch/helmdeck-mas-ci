package app.helmdeck.wear

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.dp

/**
 * The four Material icons the watch's buttons carry (Icon slot of Wear Compose
 * Material3 Button, as in the Google samples). Paths are the stock Material
 * "baseline" 24dp glyphs (Mic, VolumeUp, VolumeOff, Dashboard; Apache 2.0);
 * material-icons-extended would pull in ~11k icons for these four.
 */
private fun glyph(name: String, d: String): ImageVector =
    ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f)
        .addPath(PathParser().parsePathString(d).toNodes(), fill = SolidColor(Color.Black))
        .build()

object WearIcons {
    val Mic: ImageVector by lazy {
        glyph("Mic", "M12,14c1.66,0 2.99,-1.34 2.99,-3L15,5c0,-1.66 -1.34,-3 -3,-3S9,3.34 9,5v6c0,1.66 1.34,3 3,3zM17.3,11c0,3 -2.54,5.1 -5.3,5.1S6.7,14 6.7,11L5,11c0,3.41 2.72,6.23 6,6.72L11,21h2v-3.28c3.28,-0.48 6,-3.3 6,-6.72h-1.7z")
    }
    val VolumeUp: ImageVector by lazy {
        glyph("VolumeUp", "M3,9v6h4l5,5L12,4L7,9L3,9zM16.5,12c0,-1.77 -1.02,-3.29 -2.5,-4.03v8.05c1.48,-0.73 2.5,-2.25 2.5,-4.02zM14,3.23v2.06c2.89,0.86 5,3.54 5,6.71s-2.11,5.85 -5,6.71v2.06c4.01,-0.91 7,-4.49 7,-8.77s-2.99,-7.86 -7,-8.77z")
    }
    val VolumeOff: ImageVector by lazy {
        glyph("VolumeOff", "M16.5,12c0,-1.77 -1.02,-3.29 -2.5,-4.03v2.21l2.45,2.45c0.03,-0.2 0.05,-0.41 0.05,-0.63zM19,12c0,0.94 -0.2,1.82 -0.54,2.64l1.51,1.51C20.63,14.91 21,13.5 21,12c0,-4.28 -2.99,-7.86 -7,-8.77v2.06c2.89,0.86 5,3.54 5,6.71zM4.27,3L3,4.27 7.73,9L3,9v6h4l5,5v-6.73l4.25,4.25c-0.67,0.52 -1.42,0.93 -2.25,1.18v2.06c1.38,-0.31 2.63,-0.95 3.69,-1.81L19.73,21 21,19.73l-9,-9L4.27,3zM12,4L9.91,6.09 12,8.18L12,4z")
    }
    val Dashboard: ImageVector by lazy {
        glyph("Dashboard", "M3,13h8L11,3L3,3v10zM3,21h8v-6L3,15v6zM13,21h8L21,11h-8v10zM13,3v6h8L21,3h-8z")
    }
}
