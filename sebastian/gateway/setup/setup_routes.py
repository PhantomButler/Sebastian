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
<title>Sebastian 初始化</title>
<style>
  body { font-family: sans-serif; max-width: 480px; margin: 80px auto; padding: 0 16px; }
  h1 { font-size: 1.4rem; margin-bottom: 24px; }
  label { display: block; margin-bottom: 4px; font-size: 0.9rem; color: #555; }
  input { width: 100%; box-sizing: border-box; padding: 8px 10px;
          border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; margin-bottom: 16px; }
  button { background: #1a73e8; color: #fff; border: none; padding: 10px 24px;
           border-radius: 4px; font-size: 1rem; cursor: pointer; }
  button:disabled { opacity: 0.6; cursor: default; }
  #msg { margin-top: 16px; font-size: 0.9rem; }
</style>
</head>
<body>
<h1>欢迎使用 Sebastian 🎩</h1>
<p>首次启动需要完成初始化，请设置管家名称和访问密码。</p>
<label>您的名字</label>
<input id="name" type="text" placeholder="例如：Eric" autocomplete="name">
<label>访问密码</label>
<input id="pw" type="password" placeholder="至少 6 个字符" autocomplete="new-password">
<button id="btn" onclick="submit()">完成初始化</button>
<div id="msg"></div>
<script>
const token = new URLSearchParams(location.search).get('token') || '';
async function submit() {
  const btn = document.getElementById('btn');
  const msg = document.getElementById('msg');
  btn.disabled = true;
  msg.textContent = '正在初始化…';
  try {
    const r = await fetch('/setup/complete?token=' + encodeURIComponent(token), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: document.getElementById('name').value,
        password: document.getElementById('pw').value,
      }),
    });
    const data = await r.json();
    if (r.ok) {
      msg.style.color = 'green';
      msg.textContent = '初始化完成！Sebastian 正在重启，请稍候…';
    } else {
      msg.style.color = 'red';
      msg.textContent = data.detail || '出错了，请重试。';
      btn.disabled = false;
    }
  } catch (e) {
    msg.style.color = 'red';
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

        return JSONResponse({"ok": True, "message": "初始化完成，Sebastian 即将重启。"})

    return router
