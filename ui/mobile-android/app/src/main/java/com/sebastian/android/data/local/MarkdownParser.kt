package com.sebastian.android.data.local

interface MarkdownParser {
    fun parse(text: String): CharSequence
}
