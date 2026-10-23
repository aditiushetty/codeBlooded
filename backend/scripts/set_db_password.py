"""Put the Supabase database password into DATABASE_URL in backend/.env, then test the connection.

    uv run python -m scripts.set_db_password

If DATABASE_URL is empty it first asks for the Session pooler connection string (Supabase dashboard > Connect >
Session pooler; the "[YOUR-PASSWORD]" placeholder in it is fine). The password is typed hidden, URL-encoded (so any
characters work) and never printed.
"""

import getpass
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

import psycopg

ENV = Path(__file__).resolve().parents[1] / ".env"


def main() -> None:
    lines = ENV.read_text().splitlines()
    idx = next((i for i, line in enumerate(lines) if line.startswith("DATABASE_URL=")), None)
    url = lines[idx].split("=", 1)[1].strip().strip("\"'") if idx is not None else ""
    if "pooler.supabase.com" not in url:
        url = input("Session pooler connection string (Supabase > Connect > Session pooler): ").strip().strip("\"'")
        if "pooler.supabase.com" not in url or not url.startswith("postgres"):
            raise SystemExit("That is not a Supabase session pooler string (postgresql://postgres.<ref>:...@aws-0-"
                             "<region>.pooler.supabase.com:5432/postgres). See docs/SETUP.md.")
        if idx is None:
            lines.append("DATABASE_URL=")
            idx = len(lines) - 1
    # Drop whatever password is in it (Supabase shows "[YOUR-PASSWORD]", which urlsplit rejects as a bad IPv6 host)
    url = re.sub(r"^(postgres(?:ql)?://[^:/@]+):[^@]*@", r"\1:x@", url)
    parts = urlsplit(url)

    password = getpass.getpass("Supabase database password (hidden): ").strip()
    if not password:
        raise SystemExit("No password entered; nothing changed.")
    netloc = f"{parts.username}:{quote(password, safe='')}@{parts.hostname}:{parts.port or 5432}"
    new_url = parts._replace(netloc=netloc).geturl()

    try:
        with psycopg.connect(new_url, connect_timeout=15, prepare_threshold=None) as conn:
            conn.execute("select 1")
    except psycopg.OperationalError as e:
        reason = "wrong password" if "password authentication failed" in str(e) else re.sub(r"\S+@\S+", "", str(e))[:200]
        raise SystemExit(f"Could not connect ({reason}). backend/.env was not changed.") from None

    lines[idx] = f"DATABASE_URL={new_url}"
    ENV.write_text("\n".join(lines) + "\n")
    print("Connected to Supabase. Saved to backend/.env.")


if __name__ == "__main__":
    main()
