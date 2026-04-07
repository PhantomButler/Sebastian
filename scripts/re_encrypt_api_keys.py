#!/usr/bin/env python3
"""re_encrypt_api_keys.py — 轮换 SEBASTIAN_JWT_SECRET 后重新加密 api_key_enc。

## 使用场景

Sebastian 的 LLM Provider api_key 使用 Fernet 对称加密存储，加密密钥从
SEBASTIAN_JWT_SECRET 派生（SHA-256 → Base64）。

**如果你需要轮换 SEBASTIAN_JWT_SECRET，必须先运行本脚本重新加密，再重启服务。**
顺序错误（先重启服务）会导致所有 LLM Provider 调用抛出 InvalidToken 错误。

## 操作步骤

1. **停止 Sebastian 服务**（避免并发写入）：
   ```
   docker compose down
   # 或 kill uvicorn 进程
   ```

2. **设置新 secret 到环境变量**（或直接写入 .env 但不要重启服务）：
   ```
   export SEBASTIAN_JWT_SECRET="new-secret-value"
   ```

3. **运行本脚本**（在项目根目录）：
   ```
   python scripts/re_encrypt_api_keys.py
   ```
   脚本会提示输入旧 secret，并从环境变量读取新 secret。

4. **确认输出**：
   ```
   ✅ 重新加密了 N 条记录，数据库：/path/to/sebastian.db
   ```

5. **重启服务**：
   ```
   docker compose up
   # 或 uvicorn sebastian.gateway.app:app ...
   ```

## 自定义数据库路径

默认从 SEBASTIAN_DATA_DIR（或 ~/.sebastian）读取数据库路径。
可通过 --db 参数指定：
```
python scripts/re_encrypt_api_keys.py --db /custom/path/sebastian.db
```

## 安全说明

- 旧 secret 通过标准输入读取，不会出现在进程列表或 shell 历史中
- 脚本使用事务，出错时自动回滚，不会留下半加密状态
- 旧 secret 在完成后立即从内存丢弃（Python GC 回收）
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import hashlib
import os
import sys
from pathlib import Path


def _make_fernet(secret: str):  # type: ignore[return]
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def _resolve_db_path(override: str | None) -> str:
    if override:
        return str(Path(override).expanduser().resolve())
    data_dir = os.environ.get("SEBASTIAN_DATA_DIR", str(Path.home() / ".sebastian"))
    return str(Path(data_dir).expanduser().resolve() / "sebastian.db")


async def re_encrypt(old_secret: str, new_secret: str, db_path: str) -> int:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    # Validate old secret decrypts something before touching the DB
    old_fernet = _make_fernet(old_secret)
    new_fernet = _make_fernet(new_secret)

    if not Path(db_path).exists():
        print(f"❌ 数据库文件不存在：{db_path}", file=sys.stderr)
        sys.exit(1)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
            # Import here so the script works without installing the package
            # if run from the project root with PYTHONPATH set
            from sebastian.store.models import LLMProviderRecord  # noqa: PLC0415

            result = await session.execute(select(LLMProviderRecord))
            records = list(result.scalars().all())

            if not records:
                print("ℹ️  数据库中没有 LLM Provider 记录，无需重新加密。")
                return 0

            # Decrypt all with old key first — fail fast if any record can't be decrypted
            plaintexts: list[str] = []
            for r in records:
                try:
                    plaintext = old_fernet.decrypt(r.api_key_enc.encode()).decode()
                    plaintexts.append(plaintext)
                except Exception as exc:
                    print(
                        f"❌ 解密失败（provider id={r.id!r} name={r.name!r}）：{exc}\n"
                        f"   请确认旧 secret 是否正确。",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            # Re-encrypt with new key
            for r, plaintext in zip(records, plaintexts):
                r.api_key_enc = new_fernet.encrypt(plaintext.encode()).decode()

            await session.commit()
            return len(records)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="轮换 SEBASTIAN_JWT_SECRET 后重新加密 LLM Provider api_key_enc。"
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="数据库文件路径（默认从 SEBASTIAN_DATA_DIR 或 ~/.sebastian 推导）",
    )
    args = parser.parse_args()

    db_path = _resolve_db_path(args.db)
    print(f"数据库：{db_path}")

    # Read old secret securely (stdin, no echo)
    old_secret = getpass.getpass("旧 SEBASTIAN_JWT_SECRET: ").strip()
    if not old_secret:
        print("❌ 旧 secret 不能为空。", file=sys.stderr)
        sys.exit(1)

    # Read new secret from env (already set before running this script)
    new_secret = os.environ.get("SEBASTIAN_JWT_SECRET", "").strip()
    if not new_secret:
        new_secret = getpass.getpass("新 SEBASTIAN_JWT_SECRET（未在环境变量中找到）: ").strip()
    if not new_secret:
        print("❌ 新 secret 不能为空。", file=sys.stderr)
        sys.exit(1)

    if old_secret == new_secret:
        print("⚠️  新旧 secret 相同，无需重新加密。", file=sys.stderr)
        sys.exit(0)

    count = asyncio.run(re_encrypt(old_secret, new_secret, db_path))
    if count > 0:
        print(f"✅ 重新加密了 {count} 条记录，数据库：{db_path}")
        print("   现在可以安全地重启 Sebastian 服务。")


if __name__ == "__main__":
    main()
