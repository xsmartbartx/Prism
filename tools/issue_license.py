#!/usr/bin/env python3
"""Vendor tool: issue Prism license keys. NOT shipped in the product image.

Usage:
  python tools/issue_license.py keygen --out .secrets/license-signing-key.pem
  python tools/issue_license.py issue --key .secrets/license-signing-key.pem \\
      --customer "Acme GmbH" --email it@acme.example --plan pro --months 12 [--seats 40]

Keep the signing key offline (password manager / HSM). Anyone holding it
can mint licenses. The matching public key must be set as
VENDOR_PUBLIC_KEY in server/services/licensing.py.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PREFIX = "PRISM1"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def public_key_of(private: Ed25519PrivateKey) -> str:
    raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return _b64(raw)


def load_private(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("Not an Ed25519 key")
    return key


def sign(private: Ed25519PrivateKey, payload: dict[str, Any]) -> str:
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    sig = private.sign(f"{PREFIX}.{body}".encode())
    return f"{PREFIX}.{body}.{_b64(sig)}"


def make_payload(
    *,
    customer: str,
    email: str,
    plan: str,
    months: int | None,
    seats: int | None = None,
    workspaces: int | None = None,
    features: list[str] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    payload: dict[str, Any] = {
        "product": "prism",
        "lid": uuid.uuid4().hex[:12],
        "customer": customer,
        "email": email,
        "plan": plan,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(days=round(30.44 * months))).isoformat() if months else None,
    }
    if seats:
        payload["seats"] = seats
    if workspaces:
        payload["workspaces"] = workspaces
    if features:
        payload["features"] = features
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out", type=Path, required=True)
    i = sub.add_parser("issue")
    i.add_argument("--key", type=Path, required=True)
    i.add_argument("--customer", required=True)
    i.add_argument("--email", required=True)
    i.add_argument("--plan", choices=["pro", "business"], required=True)
    i.add_argument("--months", type=int, default=12, help="0 = perpetual")
    i.add_argument("--seats", type=int)
    i.add_argument("--workspaces", type=int)
    args = p.parse_args(argv)

    if args.cmd == "keygen":
        if args.out.exists():
            print(f"{args.out} exists; refusing to overwrite", file=sys.stderr)
            return 1
        key = Ed25519PrivateKey.generate()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        args.out.chmod(0o600)
        print(f"Private key: {args.out}\nPublic key (set VENDOR_PUBLIC_KEY): {public_key_of(key)}")
        return 0

    key = load_private(args.key)
    payload = make_payload(
        customer=args.customer,
        email=args.email,
        plan=args.plan,
        months=args.months or None,
        seats=args.seats,
        workspaces=args.workspaces,
    )
    print(sign(key, payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
