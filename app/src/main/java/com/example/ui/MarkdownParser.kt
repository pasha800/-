package com.example.ui

import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.sp
import androidx.compose.material3.ColorScheme
import androidx.compose.ui.text.withStyle

object MarkdownParser {

    fun parse(text: String, colorScheme: ColorScheme): AnnotatedString {
        return buildAnnotatedString {
            val lines = text.split("\n")
            lines.forEachIndexed { index, line ->
                val isLast = index == lines.lastIndex
                
                // Process line blocks
                when {
                    line.startsWith("# ") -> {
                        withStyle(SpanStyle(
                            fontWeight = FontWeight.Bold,
                            fontSize = 22.sp,
                            color = colorScheme.primary
                        )) {
                            append(parseInlineStyles(line.substring(2), colorScheme))
                        }
                    }
                    line.startsWith("## ") -> {
                        withStyle(SpanStyle(
                            fontWeight = FontWeight.Bold,
                            fontSize = 19.sp,
                            color = colorScheme.secondary
                        )) {
                            append(parseInlineStyles(line.substring(3), colorScheme))
                        }
                    }
                    line.startsWith("### ") -> {
                        withStyle(SpanStyle(
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 16.sp,
                            color = colorScheme.tertiary
                        )) {
                            append(parseInlineStyles(line.substring(4), colorScheme))
                        }
                    }
                    line.startsWith("> ") -> {
                        withStyle(SpanStyle(
                            fontStyle = FontStyle.Italic,
                            fontSize = 14.sp,
                            color = colorScheme.outline
                        )) {
                            append(" “ ")
                            append(parseInlineStyles(line.substring(2), colorScheme))
                            append(" ”")
                        }
                    }
                    line.startsWith("- ") || line.startsWith("* ") -> {
                        append("  •  ")
                        append(parseInlineStyles(line.substring(2), colorScheme))
                    }
                    else -> {
                        append(parseInlineStyles(line, colorScheme))
                    }
                }
                
                if (!isLast) {
                    append("\n")
                }
            }
        }
    }

    private fun parseInlineStyles(line: String, colorScheme: ColorScheme): AnnotatedString {
        return buildAnnotatedString {
            var i = 0
            while (i < line.length) {
                when {
                    // Bold-Italic (***text*** or ___text___)
                    line.startsWith("***", i) -> {
                        val end = line.indexOf("***", i + 3)
                        if (end != -1) {
                            val content = line.substring(i + 3, end)
                            withStyle(SpanStyle(
                                fontWeight = FontWeight.Bold,
                                fontStyle = FontStyle.Italic
                            )) {
                                append(content)
                            }
                            i = end + 3
                        } else {
                            append("*")
                            i++
                        }
                    }
                    // Bold (**text**)
                    line.startsWith("**", i) -> {
                        val end = line.indexOf("**", i + 2)
                        if (end != -1) {
                            val content = line.substring(i + 2, end)
                            withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                                append(content)
                            }
                            i = end + 2
                        } else {
                            append("*")
                            i++
                        }
                    }
                    // Italic (*text*)
                    line.startsWith("*", i) -> {
                        val end = line.indexOf("*", i + 1)
                        if (end != -1) {
                            val content = line.substring(i + 1, end)
                            withStyle(SpanStyle(fontStyle = FontStyle.Italic)) {
                                append(content)
                            }
                            i = end + 1
                        } else {
                            append("*")
                            i++
                        }
                    }
                    // Inline Code (`code`)
                    line.startsWith("`", i) -> {
                        val end = line.indexOf("`", i + 1)
                        if (end != -1) {
                            val content = line.substring(i + 1, end)
                            withStyle(SpanStyle(
                                fontFamily = FontFamily.Monospace,
                                background = colorScheme.surfaceVariant,
                                color = colorScheme.onSurfaceVariant
                            )) {
                                append(" $content ")
                            }
                            i = end + 1
                        } else {
                            append("`")
                            i++
                        }
                    }
                    // Links ([text](url))
                    line.startsWith("[", i) -> {
                        val labelEnd = line.indexOf("]", i)
                        if (labelEnd != -1 && labelEnd + 1 < line.length && line[labelEnd + 1] == '(') {
                            val urlEnd = line.indexOf(")", labelEnd + 2)
                            if (urlEnd != -1) {
                                val label = line.substring(i + 1, labelEnd)
                                val url = line.substring(labelEnd + 2, urlEnd)
                                withStyle(SpanStyle(
                                    color = colorScheme.primary,
                                    textDecoration = TextDecoration.Underline
                                )) {
                                    append(label)
                                }
                                i = urlEnd + 1
                            } else {
                                append("[")
                                i++
                            }
                        } else {
                            append("[")
                            i++
                        }
                    }
                    else -> {
                        append(line[i].toString())
                        i++
                    }
                }
            }
        }
    }
}
