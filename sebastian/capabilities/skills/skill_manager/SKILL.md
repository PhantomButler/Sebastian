---
name: skill_manager
description: Use when the user asks anything about Sebastian Skills, including searching registries, inspecting packages, installing, updating, removing, listing local Skills, or reading local Skill instructions.
---

Use this Skill for all Sebastian Skill-related requests.

Use the public Sebastian CLI command from PATH. Do not call installation-specific
shim paths directly:

```bash
sebastian skills search "<query>"
sebastian skills inspect <slug>
sebastian skills list
sebastian skills show <name-or-slug>
sebastian skills install <slug>
sebastian skills update <slug>
sebastian skills update --all
sebastian skills remove <slug>
```

Command reference:

```bash
# Search the remote registry.
sebastian skills search "<query>"

# Inspect remote registry metadata before install or update.
sebastian skills inspect <slug>

# List local builtin, managed, and unmanaged Skills.
sebastian skills list

# Read local Skill metadata and SKILL.md instructions.
sebastian skills show <name-or-slug>

# Install a registry Skill after inspection and user confirmation.
sebastian skills install <slug>

# Update one installed managed Skill after inspection and user confirmation.
sebastian skills update <slug>

# Update all package-managed Skills after user confirmation.
sebastian skills update --all

# Remove a managed local Skill after user confirmation.
sebastian skills remove <slug>
```

Rules:

- For local Skill usage questions, run `sebastian skills list` first if the exact name is unclear, then `sebastian skills show <name-or-slug>`.
- Do not use registry `inspect` as a substitute for local `show`; installed local Skill content is authoritative for how to use it.
- Always inspect registry metadata before install or update.
- Before install or update, summarize registry-visible metadata: registry, slug/name, version, security/moderation status, download URL/SHA if shown, and warnings.
- Do not require a bundle file summary; CLI inspect does not list files unless future registry metadata provides them.
- After install or update, report the registered runtime Skill name from the CLI output.
- Ask the user for explicit confirmation before install, update, or remove.
- Do not pass `--yes` or `--force` unless the user explicitly requested that flag in the current conversation.
- Do not pass `--allow-rename` unless the user explicitly approves the registered-name change in the current conversation.
- Never use `--force` to bypass unsafe registry security/moderation status.
- Do not auto-accept an update that changes the registered Skill name.
- Do not use `--registry` unless the user names that registry.
- Never run scripts from downloaded Skill bundles during install.
- Never use `curl | bash` or similar third-party install commands.
- After install, update, or remove, tell the user the change applies to new Sebastian sessions.
