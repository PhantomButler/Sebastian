# Engineering Guidelines

## Workflow

Every task follows this sequence — no skipping steps:

1. **Clarify** — List every ambiguous point before writing any code. If the requirement can be interpreted in more than one way, ask. State any assumptions explicitly so the user can correct them early.
2. **Plan** — For any task that touches more than one file, modifies a public interface, or changes shared data structures: write an execution plan (what changes, which files, how to verify) and share it with the user before starting. Wait for confirmation.
3. **Execute** — Implement according to the plan. Verify after each logical unit — don't batch all verification to the end.
4. **Verify** — Actually run the code or tests. Attach the real output to your response.
5. **Report** — State concisely: what was done, what the result is, and any remaining issues or limitations.

## Code Quality

- **Shortest path**: if 3 lines solve it, don't write 10.
- **No patches**: symptoms have root causes — find and fix the cause, not the symptom.
- **No over-engineering**: write only for the current requirement. Do not add abstractions, hooks, or config for hypothetical future needs.
- **No defensive padding**: only validate at real boundaries (user input, external APIs). Don't add error handling for scenarios that cannot occur.
- **Type annotations**: all Python code must have complete type annotations, including return types (`-> None` counts).
- **Naming**: functions and variables use `snake_case`, classes use `PascalCase`, constants use `SCREAMING_SNAKE_CASE`.

## Execution Safety

Assess risk before every operation:

| Operation | Action |
|---|---|
| Read / analyse / format | Execute directly |
| Write files / modify config | Announce what will change before executing |
| Network requests / system commands / deletions | State the risk explicitly, wait for user confirmation |
| Code from unknown or untrusted sources | Review before running — never execute blindly |

## Communication

The user can send messages to intervene in any session at any time. Design your responses accordingly:

- **Clarify before coding**: when requirements are ambiguous, ask — don't guess and rework.
- **Make assumptions explicit**: if the task description is incomplete, state your assumptions before acting so the user can redirect you.
- **Transparent progress**: for multi-step work, report progress at natural checkpoints so the user always knows where things stand.
- **Concise replies**: don't restate what the user said. Don't add filler phrases. Lead with the result.
- **Auditable plans**: a task plan must be specific enough that the user can spot problems before execution begins.
