import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "auth-config.js"


def build_config(url, anon_key):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or not parts.hostname.endswith(".supabase.co"):
        raise ValueError("SUPABASE_URL doit être l’adresse HTTPS de ton projet Supabase.")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("SUPABASE_URL ne doit pas contenir de chemin ni de paramètres.")
    if not anon_key:
        raise ValueError("SUPABASE_ANON_KEY est vide.")
    data = {"url": url.rstrip("/"), "anonKey": anon_key}
    return "window.SUPABASE_CONFIG = {};\n".format(
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    )


def write_config(content):
    if CONFIG_FILE.exists() and CONFIG_FILE.read_text(encoding="utf-8") == content:
        return False
    fd, temp_path = tempfile.mkstemp(prefix="auth-config-", suffix=".js", dir=str(ROOT))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
        os.replace(temp_path, CONFIG_FILE)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return True


def main():
    url = os.environ.get("SUPABASE_URL", "").strip()
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not url and not anon_key:
        print("Supabase non configuré : auth-config.js reste vide.")
        return
    if not url or not anon_key:
        raise ValueError("Ajoute les deux secrets SUPABASE_URL et SUPABASE_ANON_KEY.")
    if write_config(build_config(url, anon_key)):
        print("Configuration publique Supabase mise à jour.")
    else:
        print("Configuration Supabase déjà à jour.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
