
import sqlite3
from datetime import datetime, timezone

def init_db():
    conn = sqlite3.connect("auctions.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS bid_history (
            auction_id TEXT,
            bid REAL,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_bid(a):
    conn = sqlite3.connect("auctions.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO bid_history VALUES (?,?,?)",
        (a["auction_id"], float(a["current_bid"]["amount"]),
         datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()

def bid_velocity(aid):
    conn = sqlite3.connect("auctions.db")
    c = conn.cursor()
    c.execute("""
        SELECT bid, timestamp FROM bid_history
        WHERE auction_id=?
        ORDER BY timestamp DESC LIMIT 5
    """, (aid,))
    rows = c.fetchall()
    conn.close()

    if len(rows) < 2:
        return 0.0

    from datetime import datetime, timezone
    b0, t0 = rows[0]
    b1, t1 = rows[-1]

    t0 = datetime.fromisoformat(t0)
    t1 = datetime.fromisoformat(t1)
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    if t1.tzinfo is None:
        t1 = t1.replace(tzinfo=timezone.utc)

    dt = (t0 - t1).total_seconds() / 3600
    return 0.0 if dt <= 0 else (b0 - b1) / dt

def get_recent_bids(auction_id, limit=20):
    """
    Returns a list of recent bid amounts for sparkline rendering.
    Oldest → newest order.
    """
    conn = sqlite3.connect("auctions.db")
    c = conn.cursor()

    c.execute("""
        SELECT bid FROM bid_history
        WHERE auction_id = ?
        ORDER BY timestamp ASC
        LIMIT ?
    """, (auction_id, limit))

    rows = c.fetchall()
    conn.close()

    return [r[0] for r in rows]