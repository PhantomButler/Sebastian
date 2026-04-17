# gateway/setup — 首次启动初始化向导

> 上级：[gateway/README.md](../README.md)

首次启动时引导用户完成初始化：生成 `secret.key`、创建 owner 账号。初始化完成后服务自动退出，重启后进入正常模式。

## 目录结构

```
setup/
├── __init__.py        # 包入口（空）
├── secret_key.py      # SecretKeyManager：生成/读取/校验 secret.key 文件
├── security.py        # SetupSecurity：仅允许 localhost 或持有 one-time token 的请求访问
└── setup_routes.py    # /setup（HTML 向导页）+ /setup/complete（落库 owner 账号并退出）
```

## 模块说明

**secret_key.py** — `SecretKeyManager`
管理 `<data_dir>/secret.key` 文件的生命周期。`generate()` 生成随机 key 并以 `chmod 600` 写入；`exists()` 检查文件是否存在。整个系统的加密基础（JWT 签名 + API Key Fernet 加密）均依赖此文件。

**security.py** — `SetupSecurity`
控制 `/setup` 路由的访问权限：仅允许来自 `127.0.0.1`/`::1` 的请求，或携带正确 one-time token 的请求通过。防止初始化向导被外网访问。

**setup_routes.py** — `create_setup_router()`
注册两条路由：
- `GET /setup` — 返回内嵌 CSS/JS 的单页初始化向导 HTML
- `POST /setup/complete` — 接收 `{name, password}`，写入 DB，生成 `secret.key`，2 秒后调用 `os._exit(0)` 退出进程

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 初始化向导页面样式/文案 | [setup_routes.py](setup_routes.py) 的 `_SETUP_HTML` 字符串 |
| secret.key 生成方式或路径 | [secret_key.py](secret_key.py) 的 `SecretKeyManager` |
| 访问控制规则（IP 白名单、token 校验） | [security.py](security.py) 的 `SetupSecurity` |
| 初始化完成后的行为（退出延迟、返回消息） | [setup_routes.py](setup_routes.py) 的 `setup_complete()` |

---

> 修改本目录或模块后，请同步更新此 README。
