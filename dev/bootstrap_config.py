"""
Generate a local odoo.conf from .secrets.env for sandbox development.
Run once: python dev/bootstrap_config.py

Reads .secrets.env in the repo root and writes odoo.conf next to it.
Both files are .gitignored.
"""

import os
import pathlib

ROOT = pathlib.Path(__file__).parent.parent
SECRETS_FILE = ROOT / ".secrets.env"
ODOO_CONF = ROOT / "odoo.conf"

ADDONS_PATH_RELATIVE = ".,../odoo-17-src/addons"

CONF_TEMPLATE = """\
[options]
addons_path = {addons_path}
db_host = localhost
db_port = 5432
db_user = odoo
db_password = odoo
db_name = datev_dev
http_port = 80
log_level = info

; DATEV sandbox credentials (loaded from .secrets.env)
; These are stored as ir.config_parameter after first Settings save.
; Keep this file secret — it is .gitignored.
"""


def load_secrets() -> dict:
    secrets = {}
    if not SECRETS_FILE.exists():
        print(f"[!] {SECRETS_FILE} not found – please create it first.")
        return secrets
    for line in SECRETS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        secrets[key.strip()] = value.strip()
    return secrets


def main():
    secrets = load_secrets()
    addons_path = os.path.abspath(str(ROOT / ADDONS_PATH_RELATIVE.split(",")[0]))
    odoo_addons = os.path.abspath(
        str(ROOT.parent / "odoo-17-src" / "addons")
    )
    conf = CONF_TEMPLATE.format(addons_path=f"{ROOT},{odoo_addons}")
    ODOO_CONF.write_text(conf)
    print(f"[✓] Written {ODOO_CONF}")
    print()
    print("Next steps:")
    print(f"  1. Fill in your credentials in {SECRETS_FILE}")
    print("  2. Run: python ../odoo-17-src/odoo-bin -c odoo.conf")
    print("  3. Open http://localhost and install datev_connector")
    print("  4. Go to Settings → DATEV Cloud → Connect with DATEV")


if __name__ == "__main__":
    main()
