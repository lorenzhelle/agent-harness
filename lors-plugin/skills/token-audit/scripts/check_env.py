#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""
check_env.py - Checks whether the credentials analyze.py needs are set,
without ever printing or logging their values.

Usage:
    uv run check_env.py

Prints presence only (name + "set"/"unset") for each required variable and
exits non-zero if anything required is missing. Never echoes the actual
value of ANTHROPIC_AUTH_TOKEN / ANTHROPIC_API_KEY - use this instead of
`echo $ANTHROPIC_AUTH_TOKEN`, `env`, or `printenv` when you just need to
confirm a credential is configured.
"""
import os
import sys

REQUIRED = ["ANTHROPIC_BASE_URL"]
# Either of these satisfies the credential requirement.
AUTH_VARS = ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"]
OPTIONAL = ["ANTHROPIC_MODEL"]


def presence(name: str) -> bool:
    return bool(os.environ.get(name))


def main() -> None:
    missing = []

    for name in REQUIRED:
        ok = presence(name)
        print(f"{name}: {'set' if ok else 'unset'}")
        if not ok:
            missing.append(name)

    auth_ok = any(presence(name) for name in AUTH_VARS)
    for name in AUTH_VARS:
        print(f"{name}: {'set' if presence(name) else 'unset'}")
    if not auth_ok:
        missing.append(" or ".join(AUTH_VARS))

    for name in OPTIONAL:
        print(f"{name}: {'set' if presence(name) else 'unset (will default)'}")

    if missing:
        print(f"\nMissing: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    print("\nAll required credentials are present.")


if __name__ == "__main__":
    main()
