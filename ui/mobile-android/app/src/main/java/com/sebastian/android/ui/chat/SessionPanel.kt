package com.sebastian.android.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import com.sebastian.android.ui.common.SebastianIcons
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.snapshots.SnapshotStateMap
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sebastian.android.data.model.Session
import java.time.LocalDate

@Composable
fun SessionPanel(
    sessions: List<Session>,
    activeSessionId: String?,
    isNewSession: Boolean = false,
    onSessionClick: (Session) -> Unit,
    onNewSession: () -> Unit,
    onDeleteSession: (Session) -> Unit = {},
    onNavigateToSettings: () -> Unit = {},
    onNavigateToSubAgents: () -> Unit = {},
    onClose: () -> Unit = {},
    /** 非 null 时进入精简模式：显示 agent 名称，隐藏功能区 */
    agentName: String? = null,
    modifier: Modifier = Modifier,
) {
    val isDark = MaterialTheme.colorScheme.surface.luminance() < 0.5f

    val grouped = remember(sessions) { groupSessions(sessions) }
    val defaults = remember(grouped) { defaultExpanded(grouped, LocalDate.now()) }
    val expanded: SnapshotStateMap<String, Boolean> = rememberSaveable(
        saver = listSaver(
            save = { map -> map.entries.flatMap { listOf(it.key, it.value) } },
            restore = { flat ->
                mutableStateMapOf<String, Boolean>().apply {
                    var i = 0
                    while (i < flat.size - 1) {
                        val k = flat[i] as String
                        val v = flat[i + 1] as Boolean
                        put(k, v)
                        i += 2
                    }
                }
            },
        ),
    ) {
        mutableStateMapOf<String, Boolean>().apply { putAll(defaults) }
    }

    LaunchedEffect(defaults) {
        defaults.forEach { (k, v) -> if (!expanded.containsKey(k)) expanded[k] = v }
    }

    LaunchedEffect(activeSessionId, grouped) {
        if (activeSessionId == null) return@LaunchedEffect
        for (year in grouped.years) {
            for (month in year.months) {
                if (month.sessions.any { it.id == activeSessionId }) {
                    expanded[year.key] = true
                    expanded[month.key] = true
                    return@LaunchedEffect
                }
            }
        }
    }

    Box(modifier = modifier.fillMaxSize().statusBarsPadding()) {
        Column(modifier = Modifier.fillMaxSize()) {
            // Header
            Text(
                text = agentName ?: "Sebastian",
                style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold),
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
            )

            // Feature section — 精简模式下隐藏
            if (agentName == null) {
                Column(modifier = Modifier.padding(horizontal = 12.dp)) {
                    Text(
                        text = "功能",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(start = 4.dp, bottom = 8.dp),
                    )
                    FeatureItem(
                        label = "Sub-Agents",
                        onClick = onNavigateToSubAgents,
                    )
                    Spacer(Modifier.height(6.dp))
                    FeatureItem(
                        label = "设置",
                        onClick = onNavigateToSettings,
                    )
                    Spacer(Modifier.height(6.dp))
                    FeatureItem(
                        label = "系统总览",
                        enabled = false,
                        badgeText = "即将推出",
                        onClick = {},
                    )
                }

                HorizontalDivider(modifier = Modifier.padding(top = 12.dp))
            }

            // History section
            Column(
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 12.dp),
            ) {
                Text(
                    text = "历史对话",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 4.dp, top = 12.dp, bottom = 4.dp),
                )
                LazyColumn(modifier = Modifier.weight(1f)) {
                    grouped.recent.forEach { bucket ->
                        val isOpen = expanded[bucket.key] ?: true
                        item(key = "h-${bucket.key}") {
                            GroupHeader(
                                label = bucket.label,
                                expanded = isOpen,
                                level = 0,
                                onToggle = { expanded[bucket.key] = !isOpen },
                            )
                        }
                        if (isOpen) {
                            items(bucket.sessions, key = { it.id }) { session ->
                                SessionItem(
                                    session = session,
                                    isActive = session.id == activeSessionId,
                                    onClick = { onSessionClick(session) },
                                    onDelete = { onDeleteSession(session) },
                                )
                            }
                        }
                    }
                    grouped.years.forEach { year ->
                        val yearOpen = expanded[year.key] ?: false
                        item(key = "h-${year.key}") {
                            GroupHeader(
                                label = year.label,
                                expanded = yearOpen,
                                level = 0,
                                onToggle = { expanded[year.key] = !yearOpen },
                            )
                        }
                        if (yearOpen) {
                            year.months.forEach { month ->
                                val monthOpen = expanded[month.key] ?: false
                                item(key = "h-${month.key}") {
                                    GroupHeader(
                                        label = month.label,
                                        expanded = monthOpen,
                                        level = 1,
                                        onToggle = { expanded[month.key] = !monthOpen },
                                    )
                                }
                                if (monthOpen) {
                                    items(month.sessions, key = { it.id }) { session ->
                                        SessionItem(
                                            session = session,
                                            isActive = session.id == activeSessionId,
                                            onClick = { onSessionClick(session) },
                                            onDelete = { onDeleteSession(session) },
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // New chat FAB - bottom right
        NewChatButton(
            enabled = !isNewSession,
            isDark = isDark,
            onClick = onNewSession,
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 16.dp, bottom = 40.dp),
        )
    }
}

@Composable
private fun NewChatButton(
    enabled: Boolean,
    isDark: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val containerColor = when {
        !enabled -> if (isDark) Color(0xFF333333) else Color(0xFF888888)
        isDark -> Color(0xB3464646) // rgba(70,70,70,0.95)
        else -> Color(0xFF111111)
    }
    val border = if (isDark && enabled) {
        BorderStroke(1.dp, Color.White.copy(alpha = 0.22f))
    } else {
        null
    }

    Surface(
        shape = RoundedCornerShape(22.dp),
        color = containerColor,
        border = border,
        shadowElevation = if (enabled) 4.dp else 0.dp,
        modifier = modifier
            .then(if (enabled) Modifier.clickable(onClick = onClick) else Modifier),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                Icons.Default.Edit,
                contentDescription = null,
                tint = Color.White,
                modifier = Modifier.size(16.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                text = "新对话",
                color = Color.White,
                fontSize = 14.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 0.2.sp,
            )
        }
    }
}

@Composable
private fun FeatureItem(
    label: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    badgeText: String? = null,
) {
    val borderColor = if (enabled) {
        MaterialTheme.colorScheme.outlineVariant
    } else {
        MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f)
    }

    Surface(
        shape = RoundedCornerShape(8.dp),
        border = BorderStroke(
            width = 1.dp,
            color = borderColor,
        ),
        color = MaterialTheme.colorScheme.surface,
        modifier = Modifier
            .fillMaxWidth()
            .then(if (enabled) Modifier.clickable(onClick = onClick) else Modifier),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
                color = if (enabled) {
                    MaterialTheme.colorScheme.onSurface
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
                modifier = Modifier.weight(1f),
            )
            if (badgeText != null) {
                Surface(
                    shape = RoundedCornerShape(4.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant,
                ) {
                    Text(
                        text = badgeText,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun SessionItem(
    session: Session,
    isActive: Boolean,
    onClick: () -> Unit,
    onDelete: () -> Unit,
) {
    val backgroundColor = if (isActive) {
        MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f)
    } else {
        Color.Transparent
    }

    Surface(
        shape = RoundedCornerShape(6.dp),
        color = backgroundColor,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier
                    .weight(1f)
                    .clickable(onClick = onClick)
                    .padding(horizontal = 8.dp, vertical = 10.dp),
            ) {
                Text(
                    text = session.title.ifBlank { "新对话" },
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            IconButton(onClick = onDelete) {
                Icon(
                    imageVector = SebastianIcons.Delete,
                    contentDescription = "删除会话",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(18.dp),
                )
            }
        }
    }
}

@Composable
private fun GroupHeader(
    label: String,
    expanded: Boolean,
    level: Int,
    onToggle: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onToggle)
            .padding(
                start = (4 + level * 16).dp,
                end = 4.dp,
                top = 8.dp,
                bottom = 8.dp,
            ),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = if (expanded) {
                Icons.Default.KeyboardArrowDown
            } else {
                Icons.AutoMirrored.Filled.KeyboardArrowRight
            },
            contentDescription = if (expanded) "折叠" else "展开",
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(16.dp),
        )
        Spacer(Modifier.width(4.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.labelLarge.copy(fontWeight = FontWeight.Medium),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

private fun Color.luminance(): Float {
    val r = red
    val g = green
    val b = blue
    return 0.299f * r + 0.587f * g + 0.114f * b
}
