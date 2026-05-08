---
name: skill_installer
description: Search, inspect, install, update, list, and remove Sebastian Skills through the Sebastian CLI.
---

Use this Skill when the user asks to find, install, update, list, or remove Sebastian Skills.

Use the installed CLI shim explicitly:

```bash
~/.sebastian/bin/sebastian skills search "<query>"
~/.sebastian/bin/sebastian skills inspect <slug>
~/.sebastian/bin/sebastian skills install <slug>
~/.sebastian/bin/sebastian skills list
~/.sebastian/bin/sebastian skills update <slug>
~/.sebastian/bin/sebastian skills remove <slug>
```

Rules:

- Always inspect before install or update.
- Summarize registry, slug, version, registered Skill name, files, security/moderation status, and warnings.
- Ask the user for explicit confirmation before install, update, or remove.
- Do not pass `--yes` or `--force` unless the user explicitly requested that flag in the current conversation.
- Never use `--force` to bypass unsafe registry security/moderation status.
- Do not auto-accept an update that changes the registered Skill name.
- Do not use `--registry` unless the user names that registry.
- Never run scripts from downloaded Skill bundles during install.
- Never use `curl | bash` or similar third-party install commands.
- After install, update, or remove, tell the user the change applies to new Sebastian sessions.
