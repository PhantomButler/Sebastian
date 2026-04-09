from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from sebastian.gateway.setup.secret_key import SecretKeyManager
from sebastian.gateway.setup.security import SetupSecurity
from sebastian.store.owner_store import OwnerStore

_SETUP_HTML = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sebastian 初始化</title>
<style>
  :root {
    --bg: #05070d;
    --text: #e6ecf5;
    --muted: #8a97b2;
    --accent: #5aa9ff;
    --accent-2: #8b5cf6;
    --danger: #ff7a85;
    --success: #4ade80;
    --card-bg: rgba(17, 23, 38, 0.62);
    --card-border: rgba(120, 170, 255, 0.18);
    --field-bg: rgba(9, 13, 24, 0.55);
    --field-border: rgba(120, 170, 255, 0.18);
    --focus-ring: rgba(90, 169, 255, 0.28);
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    color: var(--text);
    background: var(--bg);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32px 16px;
    position: relative;
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
  }

  /* ---- background: grid + drifting aurora blobs ---- */
  .bg {
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    overflow: hidden;
  }
  .bg::before {
    /* fine tech grid */
    content: "";
    position: absolute;
    inset: -20%;
    background-image:
      linear-gradient(rgba(120, 170, 255, 0.05) 1px, transparent 1px),
      linear-gradient(90deg, rgba(120, 170, 255, 0.05) 1px, transparent 1px);
    background-size: 44px 44px;
    mask-image: radial-gradient(ellipse at center, #000 30%, transparent 75%);
    -webkit-mask-image: radial-gradient(ellipse at center, #000 30%, transparent 75%);
  }
  .bg::after {
    /* vignette */
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(ellipse at center,
                transparent 35%, rgba(5, 7, 13, 0.9) 100%);
  }
  .blob {
    position: absolute;
    border-radius: 50%;
    filter: blur(90px);
    opacity: 0.55;
    mix-blend-mode: screen;
    will-change: transform;
  }
  .blob.b1 {
    width: 520px; height: 520px;
    background: radial-gradient(circle, #3b82f6, transparent 65%);
    top: -12%; left: -10%;
    animation: drift1 22s ease-in-out infinite alternate;
  }
  .blob.b2 {
    width: 440px; height: 440px;
    background: radial-gradient(circle, #8b5cf6, transparent 65%);
    bottom: -14%; right: -8%;
    animation: drift2 26s ease-in-out infinite alternate;
  }
  .blob.b3 {
    width: 340px; height: 340px;
    background: radial-gradient(circle, #22d3ee, transparent 65%);
    top: 55%; left: 45%;
    animation: drift3 30s ease-in-out infinite alternate;
  }
  @keyframes drift1 {
    0%   { transform: translate(0, 0) scale(1); }
    100% { transform: translate(40px, 60px) scale(1.08); }
  }
  @keyframes drift2 {
    0%   { transform: translate(0, 0) scale(1); }
    100% { transform: translate(-60px, -40px) scale(1.06); }
  }
  @keyframes drift3 {
    0%   { transform: translate(-50%, -50%) scale(1); }
    100% { transform: translate(-45%, -55%) scale(1.12); }
  }

  /* ---- card ---- */
  .card {
    position: relative;
    z-index: 1;
    width: 100%;
    max-width: 460px;
    padding: 44px 38px 34px;
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 18px;
    backdrop-filter: blur(22px) saturate(140%);
    -webkit-backdrop-filter: blur(22px) saturate(140%);
    box-shadow:
      0 40px 80px -30px rgba(0, 0, 0, 0.6),
      0 0 0 1px rgba(255, 255, 255, 0.02) inset;
  }
  .card::before {
    /* subtle top accent line */
    content: "";
    position: absolute;
    top: 0; left: 24px; right: 24px;
    height: 1px;
    background: linear-gradient(90deg,
                transparent, rgba(120, 170, 255, 0.6), transparent);
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 6px;
  }
  .brand .logo {
    width: 36px; height: 36px;
    border-radius: 10px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.2rem;
    box-shadow: 0 8px 22px -8px rgba(90, 169, 255, 0.6);
  }
  .brand .name {
    font-size: 1.45rem;
    font-weight: 600;
    letter-spacing: 0.3px;
  }
  .tagline {
    color: var(--muted);
    font-size: 0.92rem;
    line-height: 1.6;
    margin: 8px 0 26px;
  }

  .field { margin-bottom: 18px; }
  .field label {
    display: block;
    font-size: 0.78rem;
    font-weight: 500;
    letter-spacing: 0.4px;
    color: var(--muted);
    text-transform: uppercase;
    margin-bottom: 8px;
  }
  .field input {
    width: 100%;
    padding: 12px 14px;
    font-size: 0.98rem;
    color: var(--text);
    background: var(--field-bg);
    border: 1px solid var(--field-border);
    border-radius: 10px;
    transition: border-color 0.18s, box-shadow 0.18s, background 0.18s;
    font-family: inherit;
  }
  .field input::placeholder { color: rgba(138, 151, 178, 0.6); }
  .field input:focus {
    outline: none;
    border-color: var(--accent);
    background: rgba(9, 13, 24, 0.85);
    box-shadow: 0 0 0 4px var(--focus-ring);
  }
  .hint {
    font-size: 0.78rem;
    color: var(--muted);
    margin-top: 7px;
    line-height: 1.5;
  }
  button {
    width: 100%;
    margin-top: 8px;
    padding: 13px 24px;
    font-size: 1rem;
    font-weight: 600;
    letter-spacing: 0.3px;
    color: #fff;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    border: none;
    border-radius: 10px;
    cursor: pointer;
    font-family: inherit;
    box-shadow: 0 12px 28px -14px rgba(90, 169, 255, 0.65);
    transition: transform 0.08s, box-shadow 0.2s, filter 0.2s;
  }
  button:hover:not(:disabled) {
    filter: brightness(1.08);
    box-shadow: 0 16px 34px -12px rgba(90, 169, 255, 0.75);
  }
  button:active:not(:disabled) { transform: translateY(1px); }
  button:disabled { opacity: 0.55; cursor: not-allowed; }
  #msg {
    margin-top: 18px;
    font-size: 0.9rem;
    line-height: 1.55;
    min-height: 1.3em;
    color: var(--muted);
  }
  #msg.error { color: var(--danger); }
  #msg.success { color: var(--success); }
  .done-hint {
    margin-top: 12px;
    padding: 14px 16px;
    background: rgba(74, 222, 128, 0.08);
    border: 1px solid rgba(74, 222, 128, 0.28);
    border-radius: 10px;
    color: #a7f3c5;
    font-size: 0.88rem;
    line-height: 1.6;
    display: none;
  }
  .done-hint.show { display: block; }
  .done-hint code {
    background: rgba(74, 222, 128, 0.14);
    padding: 1px 6px;
    border-radius: 4px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.85em;
    color: #e6ecf5;
  }
  footer {
    margin-top: 26px;
    text-align: center;
    font-size: 0.74rem;
    letter-spacing: 0.4px;
    color: rgba(138, 151, 178, 0.7);
  }
  @media (prefers-reduced-motion: reduce) {
    .blob { animation: none !important; }
  }
</style>
</head>
<body>
<div class="bg">
  <div class="blob b1"></div>
  <div class="blob b2"></div>
  <div class="blob b3"></div>
</div>
<div class="card">
  <div class="brand">
    <div class="logo">🎩</div>
    <div class="name">Sebastian</div>
  </div>
  <p class="tagline">首次启动需要完成初始化。设置好管家名称和访问密码后，
    即可在 App 或浏览器里登录开始使用。</p>

  <form id="form" onsubmit="event.preventDefault(); submitSetup();">
    <div class="field">
      <label for="name">您的名字</label>
      <input id="name" type="text" placeholder="例如：Eric" autocomplete="name" required>
    </div>
    <div class="field">
      <label for="pw">访问密码</label>
      <input id="pw" type="password" placeholder="至少 6 个字符"
             autocomplete="new-password" required minlength="6">
      <div class="hint">密码用于登录 Sebastian，请妥善保管，暂不支持找回。</div>
    </div>
    <button id="btn" type="submit">完成初始化</button>
  </form>

  <div id="msg"></div>
  <div id="doneHint" class="done-hint">
    初始化已落盘。请关闭本页面，回到终端重新运行 <code>sebastian serve</code>
    （或再次执行一键安装脚本），然后用刚设置的账号登录。
  </div>

  <footer>SEBASTIAN · 自托管个人管家</footer>
</div>

<script>
const token = new URLSearchParams(location.search).get('token') || '';
async function submitSetup() {
  const btn = document.getElementById('btn');
  const msg = document.getElementById('msg');
  const doneHint = document.getElementById('doneHint');
  msg.className = '';
  msg.textContent = '正在初始化，请稍候…';
  btn.disabled = true;
  try {
    const r = await fetch('/setup/complete?token=' + encodeURIComponent(token), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: document.getElementById('name').value.trim(),
        password: document.getElementById('pw').value,
      }),
    });
    const data = await r.json().catch(() => ({}));
    if (r.ok) {
      msg.className = 'success';
      msg.textContent = '✓ 初始化完成';
      doneHint.classList.add('show');
      document.getElementById('form').style.display = 'none';
    } else {
      msg.className = 'error';
      msg.textContent = data.detail || '初始化失败，请重试。';
      btn.disabled = false;
    }
  } catch (e) {
    msg.className = 'error';
    msg.textContent = '网络错误：' + e;
    btn.disabled = false;
  }
}
</script>
</body>
</html>
"""


def create_setup_router(
    security: SetupSecurity,
    owner_store: OwnerStore,
    secret_key: SecretKeyManager,
) -> APIRouter:
    router = APIRouter()

    def _forbidden() -> HTTPException:  # noqa: RUF100
        return HTTPException(status_code=403, detail="Setup access denied")

    def _guard(request: Request, token: str = "") -> None:
        host = request.client.host if request.client else ""
        # Also accept token from query param
        q_token = request.query_params.get("token", "")
        effective_token = token or q_token
        if not security.is_allowed(host, effective_token):
            raise _forbidden()

    @router.get("/setup", response_class=HTMLResponse)
    async def setup_page(request: Request) -> HTMLResponse:
        host = request.client.host if request.client else ""
        token = request.query_params.get("token", "")
        if not security.is_allowed(host, token):
            raise _forbidden()
        return HTMLResponse(_SETUP_HTML)

    @router.post("/setup/complete")
    async def setup_complete(
        request: Request,
        _guard: None = Depends(_guard),
    ) -> JSONResponse:
        from sebastian.gateway.auth import hash_password, reset_signer

        body = await request.json()
        name: str = body.get("name", "").strip()
        password: str = body.get("password", "")

        if not name or not password or len(password) < 6:
            return JSONResponse(
                {"detail": "名字和密码（至少 6 位）均为必填项。"},
                status_code=422,
            )

        if await owner_store.owner_exists():
            return JSONResponse({"detail": "已存在管家账号，无法重复初始化。"}, status_code=409)

        await owner_store.create_owner(name=name, password_hash=hash_password(password))

        if not secret_key.exists():
            secret_key.generate()

        reset_signer()

        async def _exit() -> None:
            await asyncio.sleep(2)
            os._exit(0)

        asyncio.create_task(_exit())

        return JSONResponse(
            {
                "ok": True,
                "message": "初始化完成，请关闭本页并重新启动 Sebastian。",
            }
        )

    return router
