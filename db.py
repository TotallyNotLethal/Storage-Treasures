
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
            updated_at TEXT,
            facility_name TEXT,
            manual_items_json TEXT,
            manual_total_low REAL,
            manual_total_high REAL
        )
        """
    )

    try:
        c.execute("ALTER TABLE vision_results ADD COLUMN facility_name TEXT")
    except sqlite3.OperationalError:
        # Column already exists
        pass
    for col in (
        "manual_items_json TEXT",
        "manual_total_low REAL",
        "manual_total_high REAL",
    ):
        try:
            c.execute(f"ALTER TABLE vision_results ADD COLUMN {col}")
        except sqlite3.OperationalError:
            # Column already exists
            pass
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


def save_vision_result(
    auction_id,
    result,
    facility_name="",
    manual_items=None,
    manual_totals=None,
):
    conn = sqlite3.connect("auctions.db")
    c = conn.cursor()

    manual_json = None
    manual_low = None
    manual_high = None

    if manual_items is not None:
        try:
            manual_json = json.dumps(manual_items)
        except Exception:
            manual_json = None

    if manual_totals:
        manual_low = float(manual_totals.get("low", 0))
        manual_high = float(manual_totals.get("high", 0))

    c.execute(
        """
        INSERT INTO vision_results (auction_id, items_json, total_low, total_high, updated_at, facility_name, manual_items_json, manual_total_low, manual_total_high)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(auction_id) DO UPDATE SET
            items_json=excluded.items_json,
            total_low=excluded.total_low,
            total_high=excluded.total_high,
            updated_at=excluded.updated_at,
            facility_name=COALESCE(NULLIF(excluded.facility_name, ''), vision_results.facility_name),
            manual_items_json=excluded.manual_items_json,
            manual_total_low=excluded.manual_total_low,
            manual_total_high=excluded.manual_total_high
        """,
        (
            auction_id,
            json.dumps(result.get("items", [])),
            float(result.get("total_low", 0)),
            float(result.get("total_high", 0)),
            datetime.now(timezone.utc).isoformat(),
            facility_name,
            manual_json,
            manual_low,
            manual_high,
        ),
    )

    conn.commit()
    conn.close()


def load_vision_result(auction_id):
    conn = sqlite3.connect("auctions.db")
    c = conn.cursor()

    c.execute(
        """
        SELECT items_json, total_low, total_high, manual_items_json, manual_total_low, manual_total_high
        FROM vision_results
        WHERE auction_id = ?
        """,
        (auction_id,),
    )

    row = c.fetchone()
    conn.close()

    if not row:
        return None

    items_json, total_low, total_high, manual_json, manual_low, manual_high = row

    try:
        items = json.loads(items_json)
    except Exception:
        items = []

    try:
        manual_items = json.loads(manual_json) if manual_json is not None else []
    except Exception:
        manual_items = []

    return {
        "items": items,
        "total_low": float(total_low or 0),
        "total_high": float(total_high or 0),
        "manual_items": manual_items,
        "manual_total_low": float(manual_low) if manual_low is not None else None,
        "manual_total_high": float(manual_high) if manual_high is not None else None,
    }


def get_recent_vision_results(limit=10):
    conn = sqlite3.connect("auctions.db")
    c = conn.cursor()

    c.execute(
        """
        SELECT auction_id, facility_name, updated_at, total_low, total_high, manual_total_low, manual_total_high
        FROM vision_results
        ORDER BY datetime(updated_at) DESC
        LIMIT ?
        """,
        (limit,),
    )

    rows = c.fetchall()
    conn.close()

    results = []
    for row in rows:
        aid, facility_name, updated_at, low, high, manual_low, manual_high = row
        low_val = float(manual_low) if manual_low is not None else float(low or 0)
        high_val = float(manual_high) if manual_high is not None else float(high or 0)
        results.append(
            {
                "auction_id": aid,
                "facility_name": facility_name or "Unknown facility",
                "updated_at": updated_at,
                "total_low": low_val,
                "total_high": high_val,
            }
        )
    return results


def reset_manual_vision_result(auction_id):
    conn = sqlite3.connect("auctions.db")
    c = conn.cursor()
    c.execute(
        """
        UPDATE vision_results
        SET manual_items_json=NULL, manual_total_low=NULL, manual_total_high=NULL
        WHERE auction_id=?
        """,
        (auction_id,),
    )
    conn.commit()
    conn.close()
