"""Give an existing account moderator rights:  python scripts/make_moderator.py <email>"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from thinkballot.services.community import db  # noqa: E402

if __name__ == "__main__":
    conn = db.connect()
    with conn:
        n = conn.execute("UPDATE user SET is_mod = 1 WHERE email = ?", (sys.argv[1],)).rowcount
    print(f"{sys.argv[1]} is now a moderator." if n else f"No account named {sys.argv[1]}.")
    sys.exit(0 if n else 1)
