"""Configure matching CBS/CRP development credentials without printing secrets."""

import argparse
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crp-root", type=Path)
    args = parser.parse_args()
    cbs = Path(__file__).resolve().parents[1]
    crp = args.crp_root or cbs.parent.parent / "credit-risk-platform"
    local, external = cbs / ".env", crp / ".env"
    if not local.exists() or not external.exists():
        raise SystemExit(
            "Prepare the CBS and CRP .env files first; existing DB credentials are preserved."
        )
    cbs_values, crp_values = dotenv_values(local), dotenv_values(external)
    url = cbs_values.get("CRP_CUSTOMER_SERVICE_URL") or "http://127.0.0.1:8000"
    if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit(
            "This helper is for localhost development only; "
            "configure deployment secrets separately."
        )
    existing = [
        key
        for key in (
            cbs_values.get("CRP_CUSTOMER_PROVISIONING_CREDENTIAL"),
            crp_values.get("CUSTOMER_PROVISIONING_CREDENTIAL"),
        )
        if key
    ]
    if len(set(existing)) > 1:
        raise SystemExit(
            "Configured keys differ. Resolve explicitly; no credentials were overwritten."
        )
    key = existing[0] if existing else secrets.token_hex(32)
    if re.fullmatch(r"[0-9a-f]{64}", key) is None:
        raise SystemExit("Existing provisioning key has an invalid format; no changes made.")
    os.chmod(local, 0o600)
    os.chmod(external, 0o600)
    set_key(str(local), "CRP_CUSTOMER_PROVISIONING_CREDENTIAL", key)
    set_key(str(external), "CUSTOMER_PROVISIONING_CREDENTIAL", key)
    set_key(str(local), "CRP_CUSTOMER_SERVICE_URL", url)
    set_key(str(local), "CRP_CUSTOMER_ALLOW_INSECURE_HTTP", "true")
    os.chmod(local, 0o600)
    os.chmod(external, 0o600)
    print("Local onboarding configured. Restart CRP and CBS. Credentials were not printed.")


if __name__ == "__main__":
    main()
