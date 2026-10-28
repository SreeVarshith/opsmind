"""Create or update an OpsMind user.

    python -m scripts.create_user alice sre                 # asks for the password (hidden)
    python -m scripts.create_user --demo                    # creates demo users with random passwords

Roles: admin, sre (see everything), developer (no restricted control-plane runbooks).
Also sets JWT_SECRET in .env the first time, so login works right away.
"""
import argparse
import getpass
import secrets
import subprocess
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.security import get_user_store, new_secret

DEMO_FILE = Path("config/DEMO_CREDENTIALS.local.txt")  # git-ignored
DEMO_USERS = [("admin_demo", "admin"), ("sre_demo", "sre"), ("dev_demo", "developer")]


def ensure_jwt_secret() -> None:
    if not get_settings().jwt_secret:
        subprocess.run([sys.executable, "scripts/set_env.py", "JWT_SECRET", new_secret()], check=True,
                       stdout=subprocess.DEVNULL)
        print("Generated JWT_SECRET in .env (restart the API to load it)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("username", nargs="?")
    ap.add_argument("role", nargs="?", choices=["admin", "sre", "developer"])
    ap.add_argument("--demo", action="store_true", help="create demo users with random passwords")
    args = ap.parse_args()
    store = get_user_store()
    ensure_jwt_secret()

    if args.demo:
        lines = ["# OpsMind demo users (local only, never commit). Recreate with: python -m scripts.create_user --demo"]
        for username, role in DEMO_USERS:
            password = secrets.token_urlsafe(12)
            store.add(username, password, role)
            lines.append(f"{username}  role={role}  password={password}")
        DEMO_FILE.parent.mkdir(parents=True, exist_ok=True)
        DEMO_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Created {len(DEMO_USERS)} demo users. Their passwords are in {DEMO_FILE}")
        return

    if not (args.username and args.role):
        ap.error("give a username and role, or use --demo")
    password = getpass.getpass(f"Password for {args.username}: ")
    if len(password) < 10:
        sys.exit("Use at least 10 characters.")
    store.add(args.username, password, args.role)
    print(f"Saved user {args.username} ({args.role})")


if __name__ == "__main__":
    main()
