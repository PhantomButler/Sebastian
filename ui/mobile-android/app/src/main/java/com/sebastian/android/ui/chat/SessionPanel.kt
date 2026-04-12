package com.sebastian.android.ui.chat

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Session

@Composable
fun SessionPanel(
    sessions: List<Session>,
    activeSessionId: String?,
    onSessionClick: (Session) -> Unit,
    onNewSession: () -> Unit,
    onNavigateToSettings: () -> Unit,
    onNavigateToSubAgents: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxSize().statusBarsPadding()) {
        TextButton(
            onClick = onNavigateToSubAgents,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp),
        ) {
            Icon(Icons.Default.Person, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Sub-Agents", modifier = Modifier.weight(1f))
        }
        TextButton(
            onClick = onNavigateToSettings,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp),
        ) {
            Icon(Icons.Default.Settings, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("设置", modifier = Modifier.weight(1f))
        }

        HorizontalDivider()

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "会话",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier
                    .weight(1f)
                    .padding(start = 8.dp),
            )
            IconButton(onClick = onNewSession) {
                Icon(Icons.Default.Add, contentDescription = "新建会话")
            }
        }
        HorizontalDivider()

        LazyColumn(modifier = Modifier.weight(1f)) {
            items(sessions, key = { it.id }) { session ->
                ListItem(
                    headlineContent = {
                        Text(
                            text = session.title,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onSessionClick(session) },
                    colors = if (session.id == activeSessionId) {
                        ListItemDefaults.colors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant,
                        )
                    } else ListItemDefaults.colors(),
                )
            }
        }
    }
}
