"""``prism`` command-line interface."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from typing import TYPE_CHECKING

from server import __version__

if TYPE_CHECKING:
    from server.config import Settings


def _settings() -> Settings:
    from server.config import get_settings

    return get_settings()


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from server.app import create_app

    settings = _settings()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=args.host or settings.host,
        port=args.port or settings.port,
        proxy_headers=True,
        forwarded_allow_ips=args.forwarded_allow_ips,
        log_config=None,
        access_log=False,
        workers=1,
    )
    return 0


def cmd_migrate(_: argparse.Namespace) -> int:
    from server.db import Database
    from server.db.migrate import current_revision, upgrade

    settings = _settings()
    settings.ensure_dirs()
    db = Database(settings.resolved_database_url)
    upgrade(db)
    print(f"Database at revision {current_revision(db)}")
    return 0


def cmd_create_admin(args: argparse.Namespace) -> int:
    from server.db import Database
    from server.db.migrate import upgrade
    from server.services.auth import AuthService

    settings = _settings()
    settings.ensure_dirs()
    db = Database(settings.resolved_database_url)
    upgrade(db)
    if args.random_password:
        import secrets

        password = secrets.token_urlsafe(32)
    else:
        password = args.password or getpass.getpass("Password: ")
    auth = AuthService(settings.session_hours, settings.login_rate_limit)
    with db.transaction() as s:
        user, ws = auth.setup(
            s,
            email=args.email,
            name=args.name or "",
            password=password,
            workspace_name=args.workspace,
        )
    print(f"Created admin {user.email} in workspace '{ws.name}'")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from server.db import Database
    from server.db.models import User
    from server.services.auth import AuthService, check_password_policy, hash_password

    settings = _settings()
    db = Database(settings.resolved_database_url)
    password = args.password or getpass.getpass("New password: ")
    with db.transaction() as s:
        user = s.scalars(select(User).where(User.email == args.email.strip().lower())).first()
        if user is None:
            print(f"No user {args.email}", file=sys.stderr)
            return 1
        check_password_policy(password, user.email)
        user.password_hash = hash_password(password)
        user.is_active = True
        AuthService.revoke_all_sessions(s, user.id)
    print(f"Password reset for {args.email}; all sessions signed out")
    return 0


def cmd_reset_link(args: argparse.Namespace) -> int:
    """Print a single-use password link, so nobody ever has to know or send a password."""
    from sqlalchemy import select

    from server.db import Database
    from server.db.models import Membership, Role, User
    from server.services.auth import AuthService
    from server.services.context import Actor

    settings = _settings()
    db = Database(settings.resolved_database_url)
    with db.transaction() as s:
        user = s.scalars(select(User).where(User.email == args.email.strip().lower())).first()
        if user is None:
            print(f"No user {args.email}", file=sys.stderr)
            return 1
        membership = s.scalars(select(Membership).where(Membership.user_id == user.id)).first()
        if membership is None:
            print(f"{args.email} is not a member of any workspace", file=sys.stderr)
            return 1
        system = Actor(None, "cli", membership.workspace_id, Role.ADMIN, via="system")
        issued = AuthService.create_invite(
            s, system, user.email, Role(membership.role), kind="reset", hours=args.hours
        )
    print(f"{settings.base_url.rstrip('/')}/invite/{issued.secret}")
    print(f"Single use, valid {args.hours} h. Using it signs {user.email} out everywhere.")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    from pathlib import Path

    from server.backup import create_backup, prune_backups
    from server.db import Database

    settings = _settings()
    db = Database(settings.resolved_database_url)
    out = Path(args.out) if args.out else settings.backups_dir
    path = create_backup(settings, db, include_uploads=args.include_uploads, out_dir=out)
    print(f"Backup written: {path} ({path.stat().st_size / 1024 / 1024:.1f} MB)")
    if args.keep:
        for p in prune_backups(out, args.keep):
            print(f"Pruned {p.name}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    from pathlib import Path

    from server.backup import restore_backup
    from server.db import Database

    settings = _settings()
    db = Database(settings.resolved_database_url)
    manifest = restore_backup(settings, db, Path(args.archive), force=args.force)
    print(f"Restored backup from {manifest['created_at']} (Prism {manifest['version']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="prism", description="Prism self-hosted data platform")
    p.add_argument("--version", action="version", version=f"prism {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="Run the web server")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument(
        "--forwarded-allow-ips",
        default=os.environ.get("PRISM_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        help="Proxies trusted for X-Forwarded-* headers (comma list or *); "
        "default from PRISM_FORWARDED_ALLOW_IPS",
    )
    s.set_defaults(func=cmd_serve)

    m = sub.add_parser("migrate", help="Apply database migrations")
    m.set_defaults(func=cmd_migrate)

    a = sub.add_parser(
        "create-admin", help="Create the first admin account (non-interactive setup)"
    )
    a.add_argument("--email", required=True)
    a.add_argument("--name")
    a.add_argument("--password", help="Prompted when omitted")
    a.add_argument(
        "--random-password",
        action="store_true",
        help="Set an unknown random password (hand over with `prism reset-link`)",
    )
    a.add_argument("--workspace", default="My workspace")
    a.set_defaults(func=cmd_create_admin)

    r = sub.add_parser("reset-password", help="Reset a user's password")
    r.add_argument("--email", required=True)
    r.add_argument("--password", help="Prompted when omitted")
    r.set_defaults(func=cmd_reset_password)

    rl = sub.add_parser("reset-link", help="Print a single-use link to set a user's password")
    rl.add_argument("--email", required=True)
    rl.add_argument("--hours", type=int, default=24, choices=range(1, 169), metavar="1-168")
    rl.set_defaults(func=cmd_reset_link)

    b = sub.add_parser("backup", help="Write a backup archive of metadata and datasets")
    b.add_argument("--out", help="Directory for the archive (default: <data_dir>/backups)")
    b.add_argument("--include-uploads", action="store_true", help="Also archive original files")
    b.add_argument("--keep", type=int, default=0, help="Keep only the newest N archives")
    b.set_defaults(func=cmd_backup)

    rs = sub.add_parser("restore", help="Restore a backup archive into this instance")
    rs.add_argument("archive")
    rs.add_argument("--force", action="store_true", help="Replace existing data")
    rs.set_defaults(func=cmd_restore)
    return p


def main(argv: list[str] | None = None) -> int:
    from core.errors import PrismError

    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (PrismError, RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
