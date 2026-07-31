package app.swarmdeck.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Markdown for the phone, mirroring web/components/markdown.tsx on the desktop:
 * fenced code, inline code, bold/italic/strike, headings, bullet, ordered and
 * task lists, blockquotes, rules and links. Agents answer in markdown, so
 * showing it raw (which the phone used to do) throws away the structure that
 * makes a long answer readable.
 *
 * Parsing is pure Kotlin and happens once per text; rendering is a plain walk
 * over the resulting blocks.
 */
private sealed interface Block {
    data class Para(val text: String) : Block
    data class Heading(val level: Int, val text: String) : Block
    data class Bullet(val indent: Int, val marker: String, val text: String) : Block
    data class Quote(val text: String) : Block
    data class Code(val code: String, val lang: String) : Block
    data object Rule : Block
}

private val FENCE = Regex("""^\s*```(\w+)?\s*$""")
private val FENCE_END = Regex("""^\s*```\s*$""")
private val HEADING = Regex("""^(#{1,6})\s+(.*)$""")
private val RULE = Regex("""^\s*(-{3,}|\*{3,}|_{3,})\s*$""")
private val QUOTE = Regex("""^\s*>\s?""")
private val LIST = Regex("""^(\s*)([-*+]|\d+[.)])\s+(.*)$""")
private val TASK = Regex("""^\[([ xX])]\s+(.*)$""")
private val INLINE = Regex(
    """(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\n]+\*)|(~~[^~]+~~)|(\[[^\]]+]\([^)]+\))|(https?://\S+)"""
)

private fun parse(src: String): List<Block> {
    val out = mutableListOf<Block>()
    val lines = src.replace("\r\n", "\n").split("\n")
    val para = StringBuilder()
    fun flush() {
        if (para.isNotEmpty()) { out += Block.Para(para.toString().trim()); para.clear() }
    }
    var i = 0
    while (i < lines.size) {
        val line = lines[i]
        val fence = FENCE.find(line)
        when {
            fence != null -> {
                flush()
                val lang = fence.groupValues.getOrNull(1).orEmpty()
                val buf = StringBuilder(); i++
                while (i < lines.size && !FENCE_END.matches(lines[i])) { buf.appendLine(lines[i]); i++ }
                out += Block.Code(buf.toString().trimEnd(), lang)
            }
            line.isBlank() -> flush()
            HEADING.matches(line) -> {
                flush()
                val m = HEADING.find(line)!!
                out += Block.Heading(m.groupValues[1].length, m.groupValues[2])
            }
            RULE.matches(line) -> { flush(); out += Block.Rule }
            QUOTE.containsMatchIn(line) -> { flush(); out += Block.Quote(line.replace(QUOTE, "")) }
            LIST.matches(line) -> {
                flush()
                val m = LIST.find(line)!!
                val indent = m.groupValues[1].replace("\t", "  ").length
                var body = m.groupValues[3]
                val task = TASK.find(body)
                val marker = when {
                    task != null -> if (task.groupValues[1].lowercase() == "x") "☑" else "☐"
                    m.groupValues[2].first().isDigit() -> m.groupValues[2]
                    else -> "•"
                }
                if (task != null) body = task.groupValues[2]
                out += Block.Bullet(indent, marker, body)
            }
            else -> { if (para.isNotEmpty()) para.append(' '); para.append(line.trim()) }
        }
        i++
    }
    flush()
    return out
}

private fun inline(text: String, base: Color): AnnotatedString = buildAnnotatedString {
    withStyle(SpanStyle(color = base)) {
        var last = 0
        for (m in INLINE.findAll(text)) {
            if (m.range.first > last) append(text.substring(last, m.range.first))
            val t = m.value
            when {
                t.startsWith("`") -> withStyle(SpanStyle(fontFamily = FontFamily.Monospace,
                    background = Tok.surface2, color = Tok.accentSoft)) { append(t.trim('`')) }
                t.startsWith("**") || t.startsWith("__") ->
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(t.substring(2, t.length - 2)) }
                t.startsWith("~~") ->
                    withStyle(SpanStyle(textDecoration = TextDecoration.LineThrough)) { append(t.substring(2, t.length - 2)) }
                t.startsWith("[") ->
                    withStyle(SpanStyle(color = Tok.accent, textDecoration = TextDecoration.Underline)) {
                        append(t.substringAfter('[').substringBefore(']'))
                    }
                t.startsWith("http") ->
                    withStyle(SpanStyle(color = Tok.accent, textDecoration = TextDecoration.Underline)) { append(t) }
                t.startsWith("*") ->
                    withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(t.trim('*')) }
                else -> append(t)
            }
            last = m.range.last + 1
        }
        if (last < text.length) append(text.substring(last))
    }
}

@Composable
fun Markdown(src: String, fontSize: TextUnit = 13.5.sp, color: Color = Tok.txtPrimary) {
    val blocks = remember(src) { parse(src) }
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        blocks.forEach { b ->
            when (b) {
                is Block.Para -> Text(inline(b.text, color), fontSize = fontSize, lineHeight = fontSize * 1.45f)
                is Block.Heading -> Text(inline(b.text, color),
                    fontSize = when (b.level) { 1 -> 17.sp; 2 -> 15.5.sp; else -> 14.sp },
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(top = 6.dp, bottom = 1.dp))
                is Block.Bullet -> Row(Modifier.padding(start = (b.indent * 8).dp)) {
                    Text("${b.marker} ", fontSize = fontSize, color = Tok.txtTertiary)
                    Text(inline(b.text, color), fontSize = fontSize, lineHeight = fontSize * 1.4f)
                }
                is Block.Quote -> Row(Modifier.fillMaxWidth()) {
                    Box(Modifier.width(2.dp).height(18.dp).background(Tok.borderStrong))
                    Spacer(Modifier.width(8.dp))
                    Text(inline(b.text, Tok.txtSecondary), fontSize = fontSize)
                }
                is Block.Code -> CodeBlock(b.code, b.lang)
                Block.Rule -> Box(Modifier.fillMaxWidth().height(1.dp)
                    .background(Tok.borderSubtle).padding(vertical = 4.dp))
            }
        }
    }
}

/** A fenced code block: monospace, scrollable sideways, language labelled. */
@Composable
private fun CodeBlock(code: String, lang: String) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 4.dp)
            .background(Tok.surface2, RoundedCornerShape(10.dp))
            .border(1.dp, Tok.glassBorder, RoundedCornerShape(10.dp))
    ) {
        if (lang.isNotBlank()) Text(lang, fontSize = 10.sp, color = Tok.txtTertiary,
            modifier = Modifier.padding(start = 10.dp, top = 6.dp))
        Box(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(10.dp)) {
            Text(code, fontSize = 11.5.sp, fontFamily = FontFamily.Monospace,
                color = Tok.txtSecondary, lineHeight = 16.sp)
        }
    }
}
