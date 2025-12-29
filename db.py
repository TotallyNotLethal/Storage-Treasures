
import json
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

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS vision_results (
            auction_id TEXT PRIMARY KEY,
            items_json TEXT,
            total_low REAL,
            total_high REAL,
            updated_at TEXT
        )
        """
    )
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


def save_vision_result(auction_id, result):
    conn = sqlite3.connect("auctions.db")
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO vision_results (auction_id, items_json, total_low, total_high, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(auction_id) DO UPDATE SET
            items_json=excluded.items_json,
            total_low=excluded.total_low,
            total_high=excluded.total_high,
            updated_at=excluded.updated_at
        """,
        (
            auction_id,
            json.dumps(result.get("items", [])),
            float(result.get("total_low", 0)),
            float(result.get("total_high", 0)),
            datetime.now(timezone.utc).isoformat(),
        ),
    )

    conn.commit()
    conn.close()


def load_vision_result(auction_id):
    conn = sqlite3.connect("auctions.db")
    c = conn.cursor()

    c.execute(
        """
        SELECT items_json, total_low, total_high
        FROM vision_results
        WHERE auction_id = ?
        """,
        (auction_id,),
    )

    row = c.fetchone()
    conn.close()

    if not row:
        return None

    items_json, total_low, total_high = row

    try:
        items = json.loads(items_json)
    except Exception:
        items = []

    return {
        "items": items,
        "total_low": float(total_low or 0),
        "total_high": float(total_high or 0),
    }
