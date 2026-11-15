"""Configure matching auth-to-CBS registration credentials, preserving DB settings."""

import argparse
import os
import re
import secrets
from pathlib import Path

from dotenv import dotenv_values, set_key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-root", type=Path)
    parser.add_argument("--auth-in-docker", action="store_true")
    args = parser.parse_args()
    cbs = Path(__file__).resolve().parents[1]
    auth = args.auth_root or cbs.parent.parent / "login-auth-service"
    local, external = cbs / ".env", auth / ".env"
    if not local.exists() or not external.exists():
        raise SystemExit("Prepare both .env files first; database credentials are preserved.")
    cbs_values, auth_values = dotenv_values(local), dotenv_values(external)
    existing = [
        key
        for key in (
            cbs_values.get("REGISTRATION_SERVICE_CREDENTIAL"),
            auth_values.get("CBS_REGISTRATION_CREDENTIAL"),
        )
        if key
    ]
    if len(set(existing)) > 1:
        raise SystemExit("Configured keys differ. No credentials were overwritten.")
    key = existing[0] if existing else secrets.token_hex(32)
    if re.fullmatch(r"[0-9a-f]{64}", key) is None:
        raise SystemExit("Existing registration key has invalid format. No changes made.")
    for path in (local, external):
        os.chmod(path, 0o600)
    set_key(str(local), "REGISTRATION_SERVICE_CREDENTIAL", key)
    set_key(str(external), "CBS_REGISTRATION_CREDENTIAL", key)
    host = "host.docker.internal" if args.auth_in_docker else "127.0.0.1"
    set_key(str(external), "CBS_REGISTRATION_URL", f"http://{host}:8012")
    set_key(str(external), "CBS_REGISTRATION_ALLOW_LOCAL_HTTP", "true")
    for path in (local, external):
        os.chmod(path, 0o600)
    print("Local registration configured. Restart auth and the private CBS listener.")


if __name__ == "__main__":
    main()
