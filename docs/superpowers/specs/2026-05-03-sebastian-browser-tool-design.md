# Sebastian Browser Tool Design

## Context

Sebastian needs an internal browser capability for unattended web tasks. The current host
screenshot tool depends on the backend desktop session, which is not reliable for 24-hour
Ubuntu deployments when the display is off. Playwright solves a different problem: it gives
Sebastian a controlled browser it can open, inspect, operate, screenshot, and download from
without depending on a physical monitor.

This design defines the first Sebastian built-in browser tool. It is a product capability,
not an ad hoc shell script. Browser actions must go through Sebastian's tool registry,
permission gate, event logging, artifact path, and agent tool whitelist.

## Goals

- Give Sebastian a first-party browser tool backed by Playwright Chromium.
- Support unattended Ubuntu operation in headless mode by default.
- Persist cookies and local storage so users do not need to log in repeatedly.
- Keep the public tool surface small enough for the model to use reliably.
- Keep browser access inside Sebastian's permission, safety, and artifact model.
- Ship Playwright as a default runtime dependency, not an optional extra.

## Non-Goals

- No high-level `browser_task` mini-agent in the first version.
- No multi-tab public tool API in the first version.
- No screenshot image feedback into the LLM context in the first version.
- No browser data clearing UI or tool in the first version.
- No upload, PDF export, network log inspection, or browser fingerprint work in the first
  version.
- No access for Aide, Forge, or other sub-agents in the first version, including extension
  sub-agents whose manifests omit `allowed_tools`.
- No guest/family browser access in the first version. Browser state is owner-only until
  Sebastian has per-user browser profiles and user identity in tool context.

## Architecture

Implement the capability as a Native Tool package under:

```text
sebastian/capabilities/tools/browser/
```

The package has three internal layers:

- `BrowserSessionManager`: owns the Playwright lifecycle, persistent context, current page,
  download directory, screenshot directory, headless mode, viewport, and timeout settings.
- `BrowserSafetyGuard`: validates URLs and browser actions before execution.
- `BrowserNetworkGuard`: enforces browser egress safety. Application-layer URL/DNS checks are
  necessary but not sufficient; v1 must use a hard connection-time boundary such as a local
  filtering proxy or an equivalent OS/container egress firewall before claiming DNS rebinding
  cannot bypass safety rules.
- Native tools: expose a small set of registered tools to the model.

The browser tools are globally registered by the existing tool loader, but only Sebastian
receives them in its `allowed_tools` list in `sebastian/orchestrator/sebas.py`. The allowlist
model should remain the single tool visibility/execution mechanism. To avoid accidental
unrestricted extension sub-agents, the meaning of missing allowlists must be tightened:
`allowed_tools=None` should mean no capability tools at the registry/PolicyGate boundary, and
an explicit `ALL` sentinel should be required for all tools. Sub-agent manifests that omit
`allowed_tools` should resolve to protocol tools only, not all globally registered tools.

Because persistent browser state can contain the owner's authenticated sessions, the first
version should be owner-only. Guest or family identities must not be able to drive the shared
browser profile until Sebastian has per-user browser profiles or an explicit delegation model.
Current Sebastian authentication is still effectively single-owner: `/auth/login` issues an
owner token and the Phase 5 identity module is a placeholder. Under that current model,
owner-only browser access is satisfied by exposing the browser tools only through the
authenticated Sebastian owner turn path. Before true guest/family access ships, the browser
tool must either remain unavailable to those identities or the runtime must extend
`ToolCallContext` with user id/role and enforce an owner-only gate before tool execution.

Playwright is a default dependency in `pyproject.toml`. The Chromium browser binary is
installed by deployment guidance with:

```bash
python -m playwright install chromium
```

Ubuntu system dependencies are installed through:

```bash
python -m playwright install-deps chromium
```

Because `install-deps` can require `sudo`, the agentic deployment document should tell local
agents to ask the user to run or approve that command instead of silently hanging at a
password prompt.

## Tool Surface

Expose five tools:

```text
browser_open(url: str)
browser_observe(max_chars: int = 4000)
browser_act(action: str, target: str | None = None, value: str | None = None)
browser_capture(display_name: str | None = None)
browser_downloads(action: str = "list", filename: str | None = None)
```

### `browser_open`

Opens an `http` or `https` URL after safety validation. It lazily starts Chromium and reuses
the current page. It returns:

- final URL
- page title
- load status
- short page summary

### `browser_observe`

Reads the current page without taking a screenshot. It returns:

- current URL
- page title
- visible text summary
- interactive element summary
- truncation metadata

This is the model's primary way to understand a page in the first version.

### `browser_act`

Runs low-level page operations through a bounded `action` enum:

```text
click
type
press
select
wait_for_text
wait_for_selector
back
forward
reload
```

`target` may be a CSS selector or a visible text/role-oriented locator shorthand. The
implementation should prefer stable Playwright locator behavior and return deterministic
errors when a target is missing, ambiguous, or incompatible with the requested action.

### `browser_capture`

Captures the current page as a screenshot artifact and sends it to the user/event stream. The
tool result returned to the model must stay lightweight: screenshot sent, filename, URL, and
basic dimensions if available. Do not put image bytes or OCR text into the model-facing tool
result.

### `browser_downloads`

Lists or sends files from the browser download directory. Downloaded files are stored under
Sebastian's user data directory:

```text
~/.sebastian/data/browser/downloads/
```

The existing `send_file_path` path only supports images and a small set of text files. That
is not enough for browser downloads such as PDF, ZIP, XLSX, or DOCX. Implementing
`browser_downloads(action="send")` therefore requires extending the attachment/artifact layer
with a generic binary download kind, or adding a browser-specific send path with equivalent
download URL semantics. The first version should support common binary downloads rather than
pretending `send_file_path` can handle them.

The generic download artifact must be end-to-end:

- `AttachmentStore` validation/storage accepts a generic download/binary kind with a bounded
  max size and preserved MIME type.
- `gateway/routes/attachments.py` accepts and serves that kind.
- SSE and timeline payloads carry the artifact with a stable `kind`, `download_url`,
  filename, MIME type, and size.
- Android parses the new artifact kind and renders it as a downloadable file block.
- Timeline mapping tests and ChatViewModel tests cover the new artifact kind.

The tool must reject filenames that resolve outside the browser downloads directory.

## Session And Storage

Use Playwright persistent context so cookies and local storage survive Sebastian restarts.
Store browser data below the existing Sebastian data directory:

```text
~/.sebastian/data/browser/profile/
~/.sebastian/data/browser/downloads/
~/.sebastian/data/browser/screenshots/
```

The first version exposes only one current page. The internal structure may keep room for a
future page registry, but the public tool schema does not include `page_id`.

Browser operations should be serialized with an internal async lock. The browser has mutable
current-page state, so concurrent tool calls must not interleave navigation, observation,
typing, and downloads.

The manager is a long-lived runtime resource. It should be reachable from `sebastian.gateway.state`
or an equivalent gateway-owned runtime holder. Gateway lifespan shutdown must close the page,
context, browser, and Playwright driver before disposing the database engine. This ensures
cookies/local storage are flushed and no orphan Chromium process remains after shutdown.

Default runtime mode:

```text
headless = true
browser = chromium
viewport = 1280x900
timeout_ms = 30000
```

Add configuration entries equivalent to:

```text
SEBASTIAN_BROWSER_HEADLESS=true
SEBASTIAN_BROWSER_VIEWPORT=1280x900
SEBASTIAN_BROWSER_TIMEOUT_MS=30000
```

Visible browser mode is a debugging option, not the default product mode.

## Security

The browser safety guard allows only `http://` and `https://` URLs by default.

It blocks:

- `file://`
- `chrome://`
- `about:`
- `data:`
- `javascript:`
- localhost and loopback addresses
- private and link-local network ranges
- cloud metadata addresses

Localhost, loopback, LAN, and private network addresses require explicit user authorization.
The first version may return a deterministic blocked result rather than implementing a new
browser-specific allowlist UI.

URL checks must run at three points:

- before navigation, using the user-provided URL
- after DNS resolution, rejecting hostnames that resolve to loopback, private, link-local, or
  metadata addresses
- after navigation, validating the final URL after redirects

The Playwright context should also block network requests whose resolved destination falls
into a forbidden address range. This prevents a public page from causing Sebastian's browser
to request localhost, LAN, or metadata endpoints as subresources.

Application-layer request checks are only the first layer. They have a DNS time-of-check /
time-of-use gap if Chromium resolves the hostname again after Sebastian validates it. To make
the acceptance criterion "DNS rebinding cannot bypass URL safety rules" true, v1 must add one
hard egress boundary:

- Preferred: force Chromium through a local filtering proxy for all HTTP/HTTPS traffic. The
  proxy resolves the target hostname at connection time, validates the actual destination IP,
  and only then opens the upstream connection. Browser launch/config must prevent proxy
  bypass for normal web traffic.
- Acceptable alternative: run Chromium behind an OS/container egress firewall that blocks
  loopback, private, link-local, multicast, and metadata ranges regardless of application DNS
  behavior.

If neither hard boundary is implemented, the feature must not claim DNS rebinding resistance;
the acceptance criterion must be downgraded before implementation.

The application-layer resolver still needs a concrete algorithm:

- Parse with a structured URL parser, never string-prefix checks.
- Resolve hostnames through one shared async resolver utility.
- Check all A and AAAA answers with Python's `ipaddress` classification.
- Treat CNAMEs as safe only if every final A/AAAA answer is allowed.
- Re-resolve before each main-frame navigation and each routed request; do not rely on a
  long-lived cache.
- Keep any positive DNS cache short-lived and conservative.
- If resolution fails, times out, or returns an empty answer, block by default.
- Apply the same checks to IPv4 literals, IPv6 literals, bracketed IPv6, IDNA hostnames, and
  redirect targets.

Permission tiers:

- `browser_observe`: `MODEL_DECIDES`
- `browser_open`: `MODEL_DECIDES`
- `browser_act`: `MODEL_DECIDES`
- `browser_capture`: `MODEL_DECIDES`
- `browser_downloads`: `MODEL_DECIDES`

Tool descriptions must tell the model to ask for user confirmation before actions involving:

- passwords and login submission
- payment, purchase, transfer, or checkout
- deleting or modifying account data
- sending messages or publishing content
- submitting forms with meaningful external side effects

The first version uses the existing `PermissionReviewer` before tool execution; it does not
add a separate browser approval system.

`browser_observe` is not LOW risk. With persistent login state, observation can send inboxes,
banking pages, admin dashboards, or private documents into the model context and conversation
history. The tool should include the current URL/title in its reviewer-facing input when
possible, and the implementation should reject observation when there is no current page or
when the current page was not opened through the browser tool session.

Current `PolicyGate` reviews `MODEL_DECIDES` tools before tool execution and normally only
sees model-provided input. For `browser_observe`, that input is just `max_chars`, so the
reviewer would not see the current page URL/title unless the permission layer can ask the
browser runtime for safe preflight metadata first. Implement v1 with a tool-specific
review-input enricher/preflight hook in `PolicyGate`: before calling `PermissionReviewer`, the
gate may let a registered tool enrich the review input with sanitized metadata such as
current URL, title, and whether the page was opened by the browser tool session. The preflight
hook must not read page body text or sensitive form values. If the browser preflight cannot
prove there is an active browser-tool page, `browser_observe` should be blocked rather than
reviewed with incomplete context.

High-impact browser actions need a hard guard, not only a prompt instruction. Existing
`PolicyGate` approval happens before the tool executes and only sees the model-provided tool
input. It cannot know the resolved DOM element, form semantics, or current page state.
Therefore v1 must block high-impact actions detected inside `browser_act` rather than trying
to execute them after generic approval. A future version may add a browser-specific approval
helper that can ask the user about the exact resolved element, action, page URL, and form
metadata.

Before executing `browser_act`, the tool should inspect the target element and action
metadata. If the action appears to submit credentials, type into a password field, purchase,
pay, delete, publish, send a message, change account settings, or submit an externally
meaningful form, v1 returns a deterministic blocked result.

Observation privacy:

- Do not return password field values.
- Do not return full values from hidden inputs.
- Avoid echoing long form field values unless they are visibly rendered page text.
- Prefer labels, roles, placeholder text, and element summaries over raw input values.

Download handling:

- Downloads triggered by `browser_act` should be accepted by the Playwright context and saved
  into the fixed downloads directory.
- Browser tools must not honor site-provided paths outside that directory.

## Failure Behavior

Failures must return `ToolResult(ok=False, error=...)` with deterministic guidance. Errors
that should not be retried with the same input must include `Do not retry automatically`.

Important failures:

- Chromium is not installed:
  `Ask the user to run: python -m playwright install chromium`
- Ubuntu/browser system dependencies are missing:
  `Ask the user to run: python -m playwright install-deps chromium`
- URL blocked by safety guard:
  explain the blocked category and ask for explicit user authorization if appropriate
- Target missing or ambiguous:
  ask the model to observe the page and choose a more specific target
- Download path escapes the downloads directory:
  reject the request and do not retry automatically

## Deployment Documentation

Update agentic deployment guidance so local agents know:

- Playwright is installed as a default Python dependency.
- Chromium must be installed with `python -m playwright install chromium`.
- Ubuntu system dependencies may require `python -m playwright install-deps chromium`.
- Commands requiring `sudo` should be handed to the user for approval/execution.
- Mainland China users should already have pip mirrors configured before installing Python
  packages; Chromium binary download failures should be treated as network/mirror issues, not
  repeated blindly.
- New browser configuration fields must be documented in `Settings`, `.env.example`, the
  relevant README files, and agentic deployment guidance.
- Browser data directories should be created by `ensure_data_dir()` or lazily by
  `BrowserSessionManager` before launch.

## Cleanup

Browser screenshots are transient artifacts. `browser_capture` may send screenshots through
the attachment/artifact path, but temporary screenshot files under
`~/.sebastian/data/browser/screenshots/` should be deleted after sending or cleaned with a
bounded TTL, matching the host screenshot tool's behavior.

## Testing

### Unit Tests

- URL guard blocks unsupported protocols, loopback, private ranges, link-local ranges, and
  metadata addresses.
- URL guard allows ordinary public `http` and `https` URLs.
- URL guard rejects public hostnames that resolve to forbidden address ranges.
- Navigation guard rejects redirects to forbidden address ranges.
- Request guard blocks page subrequests to forbidden address ranges.
- Hard egress guard tests prove Chromium cannot connect to forbidden ranges through DNS
  rebinding or subresource requests; application-layer resolver tests alone are insufficient.
- DNS guard covers IPv4 literals, IPv6 literals, CNAME chains, A/AAAA answers, failed
  resolution, and short-lived cache behavior.
- Browser action enum values are enforced at runtime. If the existing `@tool` schema inference
  cannot express a JSON Schema enum, the tool must still validate the `action` string and
  return deterministic errors for unknown actions.
- Download path resolution rejects traversal outside the browser downloads directory.
- Generic binary browser downloads can be sent as artifacts, including common PDF, ZIP, XLSX,
  and DOCX files.
- Generic binary artifacts are covered end-to-end across `AttachmentStore`, attachment routes,
  SSE/timeline payloads, Android parsing/rendering, and mobile tests.
- `browser_observe` uses `MODEL_DECIDES` and rejects observation without an active page opened
  through the browser tool session.
- `PolicyGate` preflight/enricher tests verify `browser_observe` reviewer input includes
  sanitized current URL/title metadata before approval review.
- `browser_act` rejects unknown actions and missing required parameters.
- `browser_act` blocks detected high-impact actions in v1.
- Tool failures include deterministic guidance and `Do not retry automatically` where
  appropriate.

### Async Tool Tests

Use a fake `BrowserSessionManager` to verify:

- `browser_open` output shape.
- `browser_observe` truncation behavior.
- `browser_act` success and deterministic target errors.
- `browser_capture` emits artifact metadata without image bytes in model-facing output.
- `browser_downloads` lists and sends files only from the downloads directory.

### Optional Playwright Integration Tests

Gate real browser tests behind an environment variable, for example:

```text
SEBASTIAN_RUN_PLAYWRIGHT_TESTS=1
```

The integration test should start a temporary local HTTP server and verify:

- headless Chromium opens a page
- text can be observed
- a button can be clicked
- text can be typed
- screenshot capture produces a non-empty PNG
- a file download lands in the configured downloads directory

Because the safety policy blocks localhost by default, test code may either instantiate the
session manager directly with a test-only guard override or explicitly mark the local server
as test-authorized.

## Acceptance Criteria

- Sebastian can use the browser tools; Aide, Forge, built-in sub-agents, and extension
  sub-agents cannot see or execute them. Missing `allowed_tools` resolves to no capability
  tools/protocol-only for sub-agents, and unrestricted access requires an explicit all-tools
  sentinel rather than `None`.
- Under the current single-owner auth model, only authenticated owner turns can reach browser
  tools. Before guest/family users exist, browser access must either remain owner-only or
  `ToolCallContext` must carry user identity for an explicit owner gate.
- A headless Ubuntu deployment can open and capture web pages without a physical display.
- Browser profile data and downloads persist under Sebastian's data directory.
- Gateway shutdown closes the Playwright context/browser/driver and does not leave orphan
  Chromium processes.
- High-risk URL categories are blocked by default.
- DNS rebinding, redirects, and subresource requests cannot bypass URL safety rules because a
  connection-time proxy or OS/container egress firewall blocks forbidden destination IPs.
- Detected high-impact actions are blocked in v1.
- Downloaded files cannot escape the browser downloads directory.
- Common binary downloads can be sent to the user through the artifact/download system.
- Browser download artifacts work in backend storage, attachment routes, SSE/timeline payloads,
  and Android rendering.
- Browser observation approval review includes sanitized current URL/title metadata via a
  preflight/enricher hook, or observation is blocked.
- Observing a page does not expose password field values or hidden input values.
- Temporary browser screenshots do not accumulate without bound.
- Missing Chromium or system dependencies produce actionable errors for the deployment agent
  and user.
- The tool surface remains limited to the five browser tools above.
