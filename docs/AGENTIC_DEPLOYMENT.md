# Sebastian Agentic Deployment Guide

This guide is written for local AI coding agents such as Codex, Claude Code, or
Sebastian itself. The user should be able to paste the prompt below into an
agent, and the agent should fetch this document, inspect the machine, install
missing basics, deploy Sebastian, enable auto-start, and help connect the
Android app.

## Copy This Prompt

Use this prompt in a local AI agent:

```text
Please install and deploy Sebastian on this machine by following the official
agentic deployment guide:

https://raw.githubusercontent.com/PhantomButler/Sebastian/main/docs/AGENTIC_DEPLOYMENT.md

Read the guide first, then execute it step by step. You may inspect my local
environment, install missing developer/runtime dependencies after explaining
what you are about to do, create an isolated Python/Conda environment for
Sebastian, run the Sebastian installer, initialize the owner account, register
Sebastian as a startup service, and help me set up a reachable server URL for
the Android app.

Do not stop on simple missing-environment problems. Fix them when they are safe
and reversible. Stop and ask me only when an action needs my account login,
payment, sudo/admin approval, DNS/domain ownership, a browser verification code,
or when a network/provider outage prevents progress.
```

## Contract For The Agent

Your goal is to make Sebastian usable for a non-technical user. The user should
not need to understand Python, Conda, venv, systemd, launchd, DNS, Caddy, or
Cloudflare internals.

Follow these rules:

- Read this whole guide before changing the machine.
- Explain before installing software, changing startup services, using sudo, or
  asking the user to log in to a third-party service.
- Do not run `sudo` commands yourself by default. Local agents often cannot
  enter the user's password, and failed sudo attempts confuse non-technical
  users. When elevated privileges are required, print the exact command, explain
  why it is needed, ask the user to run it in their own terminal, and continue
  only after they paste back the result.
- Prefer safe, user-level installs over global system changes.
- Prefer an isolated Python environment over modifying the system Python.
- Do not repair Sebastian's Python runtime by default with system packages such
  as `sudo apt install python3.12-venv`, `sudo apt install python3-pip`, or
  distro Python upgrades. Use an existing Conda-compatible runtime first; if none
  exists, install Miniforge/Miniconda under the user's home directory.
- Use reproducible commands and verify each phase before moving on.
- Do not silently open paid accounts, buy domains, enter passwords, or bypass
  interactive login/verification steps.
- Stop only for blockers the agent cannot solve: payment, captcha, MFA,
  unavailable network, missing user credentials, unsupported OS, or failed
  upstream services.
- If a command fails, read the error, identify the root cause, and retry with
  the smallest correct fix. Do not repeat the same failing command blindly.

Supported primary targets:

- macOS on Apple Silicon or Intel
- Linux on Debian/Ubuntu-like distributions

Unsupported for this guide:

- Windows native installs
- iOS app builds
- Enterprise multi-user hardening

If the user is on Windows, be friendly and stop early. Say that Sebastian's
agentic installer currently supports macOS and Debian/Ubuntu-like Linux first.
Suggest using a Mac, a Linux mini PC/server, a VPS, or WSL only for advanced
users who already understand Linux networking and service management. Do not
try to improvise a native Windows install.

## Phase 0: Choose The Deployment Shape

Before asking questions, tell the user why this phase exists: Sebastian is a
personal server. The answers decide where it runs, whether the phone can reach it
outside the home, whether a real HTTPS domain is needed, and whether the service
should survive reboot/logout.

Ask the user these questions in plain language. For each question, include the
short explanation so a non-technical user understands what they are choosing:

1. Is this computer/server expected to run Sebastian every day?
   - Why it matters: Sebastian must be running somewhere for the Android app to
     talk to it. An always-on Mac, mini PC, home server, or VPS is better than a
     laptop that is often asleep.
2. Should Sebastian be reachable only at home, or also from outside the home?
   - Why it matters: home-only can use a LAN address, but outside access needs a
     secure network path such as Cloudflare Tunnel, Tailscale, or a public VPS.
3. Does the user already own a domain?
   - Why it matters: a domain lets the Android app use a normal HTTPS URL like
     `https://sebastian.example.com`. Without a domain, Cloudflare Tunnel setup
     cannot provide the preferred custom hostname flow.
4. Is the user willing to buy a low-cost domain and use Cloudflare for DNS?
   - Why it matters: this is the recommended beginner-friendly path. The user may
     buy an inexpensive domain from a registrar such as Spaceship, then point it
     to Cloudflare so the agent can configure a tunnel and HTTPS hostname.
5. Should Sebastian start automatically after reboot/login?
   - Why it matters: auto-start keeps Sebastian available after the machine
     restarts. On macOS this uses LaunchAgent; on Linux this uses a user-level
     systemd service and may need linger for reboot-time startup.

Recommended default for non-technical users:

- Run Sebastian on the user's always-on Mac, mini PC, or VPS.
- Install Sebastian as a user-level startup service.
- Use Cloudflare Tunnel with a real domain for the Android app URL.

## Phase 1: Inspect The Machine

Run these checks and summarize the result:

```bash
uname -a
whoami
pwd
command -v curl || true
command -v tar || true
command -v shasum || true
command -v python3 || true
python3 --version || true
command -v conda || true
command -v mamba || true
command -v micromamba || true
test -x "$HOME/miniconda3/bin/conda" && echo "$HOME/miniconda3/bin/conda" || true
test -x "$HOME/miniforge3/bin/conda" && echo "$HOME/miniforge3/bin/conda" || true
test -x "$HOME/anaconda3/bin/conda" && echo "$HOME/anaconda3/bin/conda" || true
command -v cloudflared || true
```

On Linux, also check:

```bash
command -v systemctl || true
systemctl --user is-system-running || true
command -v loginctl || true
```

On macOS, also check:

```bash
sw_vers
command -v brew || true
command -v launchctl || true
```

Decision rules:

- If an existing Conda-compatible runtime is present (`conda`, `mamba`,
  `micromamba`, `~/miniconda3`, `~/miniforge3`, or `~/anaconda3`), prefer it and
  create/use a `sebastian` environment with Python 3.12.
- If no Conda-compatible runtime exists, and Python 3.12+ exists with working
  `python3 -m venv`, the built-in Sebastian installer path is acceptable.
- If Python is missing, too old, externally managed, or venv creation fails, do
  not install distro Python/venv packages as the default fix. Install a
  user-level Conda-compatible runtime and create a `sebastian` environment.
- If `curl`, `tar`, or checksum tools are missing, install the smallest platform
  package that provides them. If installing that package requires sudo, hand the
  command to the user instead of running sudo yourself.
- If the user is on an unsupported OS, stop and say this guide supports macOS
  and Debian/Ubuntu-like Linux first.

## Phase 2: Prepare Python Without Making A Mess

Sebastian requires Python 3.12 or newer.

Preferred path when Conda already exists:

```bash
command -v conda || true
test -x "$HOME/miniconda3/bin/conda" && echo "$HOME/miniconda3/bin/conda" || true
test -x "$HOME/miniforge3/bin/conda" && echo "$HOME/miniforge3/bin/conda" || true
test -x "$HOME/anaconda3/bin/conda" && echo "$HOME/anaconda3/bin/conda" || true
conda env list || true
```

If a `sebastian` environment already exists, use it after verifying Python 3.12+.
If it does not exist, create it:

```bash
conda create -n sebastian python=3.12 -y
conda activate sebastian
python --version
```

If Conda is installed in a common directory but not on `PATH`, source its shell
hook or call it by full path. Do not install another Conda distribution before
checking these common locations.

Secondary path when no Conda exists but Python is already suitable:

```bash
python3 --version
python3 -m venv /tmp/sebastian-venv-check
rm -rf /tmp/sebastian-venv-check
```

If that works and the user prefers not to install Conda, continue to Phase 3.

Fallback path when Python is missing or unsuitable:

1. Explain to the user that you will install a user-level Conda-compatible
   Python runtime to avoid changing system Python.
2. Prefer Miniforge on macOS Apple Silicon and Linux. Miniconda is acceptable
   when Miniforge is unavailable.
3. Install it under the user's home directory.
4. Create and activate an environment named `sebastian` with Python 3.12.

Example Conda environment commands after Conda is installed:

```bash
conda create -n sebastian python=3.12 -y
conda activate sebastian
python --version
```

Do not continue until `python --version` or `python3 --version` reports 3.12 or
newer in the environment that will run the installer.

Important: if `python3 -m venv` fails because `ensurepip` or `venv` is missing,
do not default to `sudo apt install python3.12-venv`. That changes system Python
state and teaches users to depend on distro-specific packaging. Use the
Conda-compatible path above unless the user explicitly asks for a system Python
deployment.

## Phase 3: Install Sebastian

Use the official installer from the latest release:

```bash
curl -fsSL https://raw.githubusercontent.com/PhantomButler/Sebastian/main/bootstrap.sh | bash
```

The installer will:

- download the latest backend release
- verify SHA256 checksums
- unpack into `~/.sebastian/app`
- create `.venv`
- install Python dependencies
- launch the first-run setup flow
- optionally register Sebastian as a startup service

If `~/.sebastian/app` already contains Sebastian, do not overwrite it. Use:

```bash
cd ~/.sebastian/app
.venv/bin/sebastian update
```

If setup opens a browser, ask the user to complete the owner name and password.
If the machine is headless, use:

```bash
~/.sebastian/app/.venv/bin/sebastian init --headless
```

Verify installation:

```bash
~/.sebastian/app/.venv/bin/sebastian status
~/.sebastian/app/.venv/bin/sebastian serve --host 127.0.0.1 --port 8823
```

If you start `serve` in the foreground for verification, stop it with Ctrl+C
after confirming the setup page or server starts correctly.

## Phase 4: Enable Startup Service

If the user wants Sebastian to start automatically:

```bash
~/.sebastian/app/.venv/bin/sebastian service install
~/.sebastian/app/.venv/bin/sebastian service status
```

On macOS, this creates:

```text
~/Library/LaunchAgents/com.sebastian.plist
```

On Linux, this creates:

```text
~/.config/systemd/user/sebastian.service
```

Linux note: if the user wants Sebastian to start after a reboot before the user
logs in, systemd user services may need linger:

```bash
sudo loginctl enable-linger "$USER"
```

This requires sudo. Do not run it yourself. Explain that it lets a Linux
user-level service start after reboot before login, then ask the user to run the
command in their own terminal and paste back the result.

Verify:

```bash
~/.sebastian/app/.venv/bin/sebastian service status
```

## Phase 5: Choose Network Access

Recommended order for non-technical users:

1. Cloudflare domain + Cloudflare Tunnel
2. Tailscale
3. LAN-only
4. VPS/public server + Caddy

### Option A: Cloudflare Domain + Tunnel

This is the recommended public-access path for most users:

- The Android app gets a normal HTTPS URL.
- No router port forwarding is needed.
- The phone does not need an extra VPN app.
- Cloudflare handles public TLS.
- Sebastian remains bound to `127.0.0.1:8823` locally.

Human-only prerequisites:

1. The user buys a low-cost domain from a registrar such as Spaceship. Numeric
   `.xyz` domains are often inexpensive, but the user must check the current
   price before buying.
2. The user creates or logs into a Cloudflare account.
3. The user adds the domain to Cloudflare.
4. The user changes the registrar nameservers to the Cloudflare nameservers.
5. The user waits until Cloudflare says the domain is active.

Stop here if the user has not completed domain purchase and Cloudflare
nameserver setup. Give them plain-language instructions and resume after they
confirm Cloudflare shows the domain as active.

Install `cloudflared`:

macOS with Homebrew:

```bash
brew install cloudflared
```

Debian/Ubuntu: prefer Cloudflare's official package instructions for the
specific distribution. If package setup is unavailable, use Cloudflare's
published binary for the user's CPU architecture.

Login:

```bash
cloudflared tunnel login
```

This opens a browser. Ask the user to log into Cloudflare and choose the domain.

Create the tunnel:

```bash
cloudflared tunnel create sebastian
cloudflared tunnel route dns sebastian sebastian.example.com
```

Replace `sebastian.example.com` with the user's chosen hostname.

Create config:

```bash
mkdir -p ~/.cloudflared
cloudflared tunnel list
```

Find the tunnel UUID and credentials file path, then write
`~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /Users/<USER>/.cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: sebastian.example.com
    service: http://127.0.0.1:8823
  - service: http_status:404
```

Run and verify:

```bash
cloudflared tunnel run sebastian
```

In another terminal:

```bash
curl -I https://sebastian.example.com
```

Then install the tunnel as a service if appropriate:

```bash
cloudflared service install
```

`cloudflared service install` may require elevated privileges depending on the
platform. Explain before proceeding.

Final Android server URL:

```text
https://sebastian.example.com
```

Privacy note: Cloudflare Tunnel terminates TLS at Cloudflare's edge. This is
convenient and usually the smoothest setup for beginners, but users with strict
privacy requirements may prefer Tailscale.

### Option B: Tailscale

Use this when the user prioritizes private networking over avoiding an extra
phone app.

- Install Tailscale on the Sebastian host and Android phone.
- Log into the same tailnet.
- Use MagicDNS and HTTPS certificates if available.
- Connect the Android app to the Tailscale HTTPS hostname.

See the traditional deployment guide for the full Tailscale flow:

```text
https://github.com/PhantomButler/Sebastian/blob/main/docs/DEPLOYMENT.md
```

### Option C: LAN-only

Use this for the fastest home-only setup.

Start Sebastian:

```bash
~/.sebastian/app/.venv/bin/sebastian serve --host 0.0.0.0 --port 8823
```

Find the host IP:

macOS:

```bash
ipconfig getifaddr en0
```

Linux:

```bash
hostname -I | awk '{print $1}'
```

Android server URL:

```text
http://<LAN-IP>:8823
```

LAN-only HTTP may not work with release APKs that require HTTPS. Prefer
Cloudflare Tunnel for normal phone use.

### Option D: VPS/Public Server + Caddy

Use this when the user already has a VPS and wants a traditional public server.

- Keep Sebastian bound to `127.0.0.1:8823`.
- Point DNS to the VPS.
- Install Caddy.
- Reverse proxy `https://sebastian.example.com` to `127.0.0.1:8823`.
- Open only ports 80 and 443.
- Do not expose port 8823 publicly.

Prefer Cloudflare Tunnel for beginners because it avoids firewall and reverse
proxy maintenance.

## Phase 6: Install And Connect Android

Ask the user to download the latest APK from:

```text
https://github.com/PhantomButler/Sebastian/releases
```

Then:

1. Install the APK on Android.
2. Open Sebastian.
3. Go to Settings -> Connection.
4. Enter the final server URL:
   - Cloudflare: `https://sebastian.example.com`
   - Tailscale: the tailnet HTTPS URL
   - LAN: `http://<LAN-IP>:8823`
5. Log in with the owner account created during setup.
6. Go to Settings -> Providers and add the LLM provider API key.

## Phase 7: Final Verification

Verify all of this before declaring success.

First verify the local process from the host machine:

```bash
~/.sebastian/app/.venv/bin/sebastian service status
curl -I http://127.0.0.1:8823 || true
```

Then verify the actual URL the Android phone should use.

For Cloudflare:

```bash
cloudflared tunnel list
curl -I https://sebastian.example.com
```

For Tailscale, verify the selected tailnet HTTPS URL from the host and, if
possible, from the phone browser.

For LAN-only, do not give the user `127.0.0.1`. That address means "this same
machine" and will not work from the phone. Find and show the machine's LAN IP:

macOS:

```bash
ipconfig getifaddr en0 || ipconfig getifaddr en1
```

Linux:

```bash
hostname -I | awk '{print $1}'
```

Then test and give the user:

```text
http://<LAN-IP>:8823
```

For example:

```text
http://192.168.1.23:8823
```

Ask the user to confirm:

- The Android app opens.
- Login succeeds.
- Settings -> Providers accepts an API key.
- A new chat can send a message and receive a response.

## Troubleshooting

### Python Is Missing Or Too Old

Install a user-level Conda-compatible runtime and create a Python 3.12
environment. Do not fight the system Python.

### GitHub Download Fails

Check network access to:

```text
https://github.com/PhantomButler/Sebastian
https://raw.githubusercontent.com/PhantomButler/Sebastian/main/bootstrap.sh
```

If GitHub is blocked or down, stop and explain the network blocker.

### pip Install Fails

Check whether the active Python is 3.12+, whether the venv exists, and whether
the error is a network/index problem or a compiler/system dependency problem.
Fix the smallest missing dependency, then retry.

### Service Install Fails

Run:

```bash
~/.sebastian/app/.venv/bin/sebastian service status
```

Then inspect:

```text
~/.sebastian/logs/service.err.log
~/.sebastian/logs/main.log
```

On Linux, check user systemd availability and linger. On macOS, check whether
the LaunchAgent plist exists and whether `launchctl list com.sebastian` works.

### Cloudflare Hostname Does Not Work

Check:

- The domain is active in Cloudflare.
- The hostname DNS route exists.
- The tunnel is running.
- The `~/.cloudflared/config.yml` hostname matches the intended URL.
- Sebastian is reachable locally on `127.0.0.1:8823`.

### Android Cannot Connect

Check:

- The server URL includes `https://` for Cloudflare/Tailscale/public setups.
- The URL has no trailing spaces.
- Sebastian is running.
- The phone has internet access.
- The Cloudflare/Tailscale hostname works from the phone browser.
