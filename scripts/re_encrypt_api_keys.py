#!/usr/bin/env python3
"""re_encrypt_api_keys.py — 轮换 secret.key 后重新加密 api_key_enc。

## 使用场景

Sebastian 的 LLM Provider api_key 使用 Fernet 对称加密存储，加密密钥从
secret.key 文件内容派生（SHA-256 → Base64）。

**如果你需要轮换 secret.key，必须先运行本脚本重新加密，再重启服务。**
顺序错误（先重启服务）会导致所有 LLM Provider 调用抛出 InvalidToken 错误。

## 操作步骤

1. **停止 Sebastian 服务**（避免并发写入）：
   ```
   sebastian stop
   # 或 kill uvicorn 进程
   ```

2. **替换 secret.key 文件**：
   ```
   # 备份旧的
   cp ~/.sebastian/secret.key ~/.sebastian/secret.key.bak

   # 生成新的
   python3 -c "import secrets; print(secrets.token_urlsafe(32))" > ~/.sebastian/secret.key
   chmod 600 ~/.sebastian/secret.key
   ```

3. **运行本脚本**（在项目根目录）：
   ```
   python scripts/re_encrypt_api_keys.py
   ```
   脚本会提示输入旧 secret（即 secret.key.bak 的内容），
   并从当前 secret.key 读取新 secret。

4. **确认输出**：
   ```
   ✅ 重新加密了 N 条记录，数据库：/path/to/sebastian.db
   ```

5. **重启服务**：
   ```
   sebastian serve
   ```

## 自定义路径

默认从 SEBASTIAN_DATA_DIR（或 ~/.sebastian）读取数据库和 secret.key。
可通过参数指定：
```
python scripts/re_encrypt_api_keys.py --db /path/to/sebastian.db --secret-key /path/to/secret.key
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


def _resolve_data_dir(override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    default = os.environ.get("SEBASTIAN_DATA_DIR", str(Path.home() / ".sebastian"))
    return Path(default).expanduser().resolve()


def _resolve_db_path(data_dir: Path, db_override: str | None) -> str:
    if db_override:
        return str(Path(db_override).expanduser().resolve())
    return str(data_dir / "sebastian.db")


def _resolve_secret_key_path(data_dir: Path, key_override: str | None) -> Path:
    if key_override:
        return Path(key_override).expanduser().resolve()
    return data_dir / "secret.key"


async def re_encrypt(old_secret: str, new_secret: str, db_path: str) -> int:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    old_fernet = _make_fernet(old_secret)
    new_fernet = _make_fernet(new_secret)

    if not Path(db_path).exists():
        print(f"❌ 数据库文件不存在：{db_path}", file=sys.stderr)
        sys.exit(1)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
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
        description="轮换 secret.key 后重新加密 LLM Provider api_key_enc。"
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="数据库文件路径（默认从 SEBASTIAN_DATA_DIR 或 ~/.sebastian 推导）",
    )
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        help="数据目录（默认 SEBASTIAN_DATA_DIR 或 ~/.sebastian）",
    )
    parser.add_argument(
        "--secret-key",
        metavar="PATH",
        help="新 secret.key 文件路径（默认 <data-dir>/secret.key）",
    )
    args = parser.parse_args()

    data_dir = _resolve_data_dir(args.data_dir)
    db_path = _resolve_db_path(data_dir, args.db)
    secret_key_path = _resolve_secret_key_path(data_dir, args.secret_key)

    print(f"数据目录：{data_dir}")
    print(f"数据库：  {db_path}")
    print(f"密钥文件：{secret_key_path}")

    # Read new secret from secret.key file
    if not secret_key_path.exists():
        print(f"❌ 新密钥文件不存在：{secret_key_path}", file=sys.stderr)
        print("   请先生成新的 secret.key 文件。", file=sys.stderr)
        sys.exit(1)
    new_secret = secret_key_path.read_text(encoding="utf-8").strip()

    # Read old secret securely (stdin, no echo)
    old_secret = getpass.getpass("旧 secret.key 内容: ").strip()
    if not old_secret:
        print("❌ 旧 secret 不能为空。", file=sys.stderr)
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
