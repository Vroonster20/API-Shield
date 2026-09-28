"""Local operator commands; no administrative action is exposed on the gateway."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

import aiosqlite

from .admin_auth import AuthError, AuthService
from .config import ConfigConflict, ConfigStore
from .contracts import ConfigInvalid
from .db import Database, StorageUnavailable
from .settings import Settings, SettingsError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m shield_api.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Create and migrate the local runtime store")
    for name in ("bootstrap-admin", "reset-password"):
        command = commands.add_parser(name)
        command.add_argument("--username", required=True)
        command.add_argument("--password-file", type=Path)
    apply = commands.add_parser("apply-config")
    apply.add_argument("--config-file", required=True, type=Path)
    apply.add_argument("--expected-version", help="Current desired version, or 'none' for the first save")
    return parser


def _password(path: Path | None) -> str:
    if path is None:
        first = getpass.getpass("Administrator password: ")
        second = getpass.getpass("Confirm password: ")
        if first != second:
            raise ValueError("Passwords do not match")
        return first
    if path.stat().st_size > 1024:
        raise ValueError("Password file is too large")
    return path.read_text(encoding="utf-8")


def _ensure_secret(settings: Settings) -> None:
    path = settings.rate_secret_file
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        settings.load_rate_secret()
        return
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(secrets.token_bytes(32))
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def _run(args: argparse.Namespace) -> str:
    settings = Settings.from_env()
    db = Database(settings.db_path)
    try:
        if args.command == "migrate":
            _ensure_secret(settings)
            await db.initialize()
            return "Runtime store ready"
        if not db.path.is_file():
            raise StorageUnavailable("Runtime store has not been migrated")
        async with db.read() as conn:
            row = await (
                await conn.execute("SELECT singleton FROM runtime_config WHERE singleton=1")
            ).fetchone()
        if row is None:
            raise StorageUnavailable("Runtime store has not been migrated")
        if args.command in ("bootstrap-admin", "reset-password"):
            password = _password(args.password_file)
            auth = AuthService(db, settings.load_rate_secret())
            if args.command == "bootstrap-admin":
                await auth.bootstrap_admin(args.username, password)
                return "Administrator created"
            await auth.reset_password(args.username, password)
            return "Password reset; sessions revoked"
        if args.command == "apply-config":
            if args.config_file.stat().st_size > 512 * 1024:
                raise ValueError("Config file is too large")
            document = json.loads(args.config_file.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ConfigInvalid(["Configuration must be an object"])
            store = ConfigStore(db, settings.load_registry())
            if args.expected_version is None:
                expected, _ = await store.load_desired()
            elif args.expected_version == "none":
                expected = None
            else:
                expected = int(args.expected_version)
                if expected < 1:
                    raise ValueError("Expected version must be positive")
            async with db.read() as conn:
                row = await (
                    await conn.execute("SELECT id FROM admins ORDER BY created_at_ms LIMIT 1")
                ).fetchone()
            if row is None:
                raise ValueError("Bootstrap an administrator first")
            pending = await store.apply_config(expected, document, row["id"])
            return f"Configuration version {pending.desired_version} saved; pending gateway apply"
        raise ValueError("Unknown command")
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print(asyncio.run(_run(args)))
        return 0
    except (
        AuthError,
        ConfigConflict,
        ConfigInvalid,
        SettingsError,
        StorageUnavailable,
        OSError,
        ValueError,
        aiosqlite.Error,
    ) as exc:
        # Never print validation input, credential material, or internal paths.
        code = exc.code if isinstance(exc, AuthError) else type(exc).__name__
        print(f"Operation failed: {code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
