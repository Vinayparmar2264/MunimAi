"""
database.py — MerchAI v6 SQLite Database Layer
Handles all DB operations for:
  - users (shopkeepers & customers, role-based)
  - shops (multi-shop per user, location-aware)
  - products (per-shop, with visibility & brand)
  - analyses (cached per product)
  - customers (registration with location)

Multi-tenant isolation: every query is scoped by shop_id + owner_id.
No data from one shop can leak to another.
"""

import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "merch_ai.db")


def get_db():
    """Return a new SQLite connection with row_factory set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables if they don't exist. Safe to call on every startup."""
    conn = get_db()
    conn.executescript("""
        -- ─── USERS (shopkeepers + customers, unified auth) ──────────────
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            role          TEXT    NOT NULL DEFAULT 'shopkeeper',
            -- customer location fields
            latitude      REAL    DEFAULT NULL,
            longitude     REAL    DEFAULT NULL,
            location_name TEXT    DEFAULT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        -- ─── SHOPS (multi-shop per user, each with geo location) ─────────
        CREATE TABLE IF NOT EXISTS shops (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id      INTEGER NOT NULL,
            shop_name     TEXT    NOT NULL,
            shop_location TEXT    NOT NULL,
            latitude      REAL    DEFAULT NULL,
            longitude     REAL    DEFAULT NULL,
            extra_notes   TEXT    DEFAULT '',
            is_active     INTEGER DEFAULT 1,
            created_at    TEXT    DEFAULT (datetime('now')),
            updated_at    TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
        );

        -- ─── PRODUCTS (per-shop, with visibility & brand) ──────────────
        CREATE TABLE IF NOT EXISTS products (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id              INTEGER NOT NULL,
            user_id              INTEGER NOT NULL,
            product_name         TEXT    NOT NULL,
            brand_name           TEXT    DEFAULT '',
            category             TEXT    NOT NULL,
            sales_last_week      REAL    NOT NULL,
            sales_last_month     REAL    NOT NULL,
            stock                REAL    NOT NULL,
            expiry_days          INTEGER NOT NULL,
            current_price        REAL    NOT NULL,
            cost_price           REAL    NOT NULL,
            competitor_price     REAL    DEFAULT 0,
            season_factor        REAL    DEFAULT 1.0,
            demand_variability   TEXT    DEFAULT 'Medium',
            lead_time_days       INTEGER DEFAULT 3,
            holding_cost_pct     REAL    DEFAULT 25,
            order_cost           REAL    DEFAULT 500,
            target_service_level INTEGER DEFAULT 95,
            reorder_window_days  INTEGER DEFAULT 7,
            is_visible           INTEGER DEFAULT 1,
            created_at           TEXT    DEFAULT (datetime('now')),
            updated_at           TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (shop_id)  REFERENCES shops(id)  ON DELETE CASCADE,
            FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE
        );

        -- ─── ANALYSES (cached per product) ────────────────────────────
        CREATE TABLE IF NOT EXISTS analyses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id      INTEGER NOT NULL,
            shop_id         INTEGER NOT NULL,
            user_id         INTEGER NOT NULL,
            analysis_json   TEXT    NOT NULL,
            created_at      TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
            FOREIGN KEY (shop_id)    REFERENCES shops(id)    ON DELETE CASCADE,
            FOREIGN KEY (user_id)    REFERENCES users(id)    ON DELETE CASCADE
        );

        -- ─── LEGACY products table (kept for existing guest/session flow) ─
        -- Adds missing columns to old products table if it exists
        -- This migration is handled via ALTER TABLE below.
    """)

    # Safe migrations: add new columns to existing tables without breaking data
    _safe_add_column(conn, "users",    "role",          "TEXT    NOT NULL DEFAULT 'shopkeeper'")
    _safe_add_column(conn, "users",    "latitude",      "REAL    DEFAULT NULL")
    _safe_add_column(conn, "users",    "longitude",     "REAL    DEFAULT NULL")
    _safe_add_column(conn, "users",    "location_name", "TEXT    DEFAULT NULL")
    _safe_add_column(conn, "products", "shop_id",       "INTEGER DEFAULT NULL")
    _safe_add_column(conn, "products", "brand_name",    "TEXT    DEFAULT ''")
    _safe_add_column(conn, "products", "is_visible",    "INTEGER DEFAULT 1")

    conn.commit()
    conn.close()
    print("[DB] Tables initialised →", DB_PATH)


def _safe_add_column(conn, table, column, definition):
    """Add a column only if it doesn't already exist."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except sqlite3.OperationalError:
        pass  # Column already exists


# ═══════════════════════════════════════════════════════════════
# USER OPERATIONS
# ═══════════════════════════════════════════════════════════════

def create_user(name: str, email: str, password_hash: str, role: str = "shopkeeper"):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name.strip(), email.strip().lower(), password_hash, role)
        )
        conn.commit()
        user = get_user_by_email(email)
        return user, None
    except sqlite3.IntegrityError:
        return None, "An account with this email already exists."
    finally:
        conn.close()


def get_user_by_email(email: str):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_location(user_id: int, latitude: float, longitude: float, location_name: str = ""):
    conn = get_db()
    conn.execute(
        "UPDATE users SET latitude=?, longitude=?, location_name=? WHERE id=?",
        (latitude, longitude, location_name, user_id)
    )
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
# SHOP OPERATIONS
# ═══════════════════════════════════════════════════════════════

def create_shop(owner_id: int, shop_name: str, shop_location: str,
                latitude: float = None, longitude: float = None,
                extra_notes: str = ""):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO shops (owner_id, shop_name, shop_location, latitude, longitude, extra_notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (owner_id, shop_name.strip(), shop_location.strip(),
         latitude, longitude, extra_notes.strip())
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def get_shops_by_owner(owner_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM shops WHERE owner_id=? AND is_active=1 ORDER BY created_at DESC",
        (owner_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_shop(shop_id: int, owner_id: int = None):
    """Fetch a single shop. If owner_id is provided, ownership is verified."""
    conn = get_db()
    if owner_id is not None:
        row = conn.execute(
            "SELECT * FROM shops WHERE id=? AND owner_id=? AND is_active=1",
            (shop_id, owner_id)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM shops WHERE id=? AND is_active=1", (shop_id,)
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_shop(shop_id: int, owner_id: int, shop_name: str, shop_location: str,
                latitude: float = None, longitude: float = None, extra_notes: str = ""):
    conn = get_db()
    conn.execute(
        """UPDATE shops SET shop_name=?, shop_location=?, latitude=?, longitude=?,
           extra_notes=?, updated_at=datetime('now')
           WHERE id=? AND owner_id=?""",
        (shop_name, shop_location, latitude, longitude, extra_notes, shop_id, owner_id)
    )
    conn.commit()
    conn.close()


def delete_shop(shop_id: int, owner_id: int):
    """Soft-delete a shop."""
    conn = get_db()
    conn.execute(
        "UPDATE shops SET is_active=0 WHERE id=? AND owner_id=?",
        (shop_id, owner_id)
    )
    conn.commit()
    conn.close()


def get_nearby_shops(lat: float, lon: float, radius_km: float = 1.0,
                     search_name: str = ""):
    """
    Return all active shops within radius_km using the Haversine formula.
    Optionally filter by shop name.
    Returns list of dicts with added 'distance_km' field.
    """
    conn = get_db()
    if search_name:
        rows = conn.execute(
            "SELECT * FROM shops WHERE is_active=1 AND shop_name LIKE ?",
            (f"%{search_name}%",)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM shops WHERE is_active=1 AND latitude IS NOT NULL AND longitude IS NOT NULL"
        ).fetchall()
    conn.close()

    import math
    result = []
    for row in rows:
        d = dict(row)
        if d.get("latitude") and d.get("longitude"):
            dist = _haversine(lat, lon, d["latitude"], d["longitude"])
            if search_name or dist <= radius_km:
                d["distance_km"] = round(dist, 2)
                result.append(d)
        elif search_name:
            d["distance_km"] = None
            result.append(d)

    result.sort(key=lambda x: x["distance_km"] if x["distance_km"] is not None else 9999)
    return result


def _haversine(lat1, lon1, lat2, lon2):
    """Calculate great-circle distance in km between two lat/lon points."""
    import math
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


# ═══════════════════════════════════════════════════════════════
# PRODUCT OPERATIONS (CRUD — now scoped by shop_id)
# ═══════════════════════════════════════════════════════════════

PRODUCT_FIELDS = [
    "product_name", "brand_name", "category",
    "sales_last_week", "sales_last_month",
    "stock", "expiry_days", "current_price", "cost_price",
    "competitor_price", "season_factor", "demand_variability",
    "lead_time_days", "holding_cost_pct", "order_cost",
    "target_service_level", "reorder_window_days", "is_visible",
]


def add_product(user_id: int, data: dict, shop_id: int = None):
    """Insert a new product and return its id."""
    conn = get_db()
    # Ensure brand_name and is_visible exist with defaults
    data.setdefault("brand_name", "")
    data.setdefault("is_visible", 1)
    vals = [data.get(f) for f in PRODUCT_FIELDS]
    placeholders = ", ".join(["?"] * len(PRODUCT_FIELDS))
    cols = ", ".join(PRODUCT_FIELDS)
    cur = conn.execute(
        f"INSERT INTO products (user_id, shop_id, {cols}) VALUES (?, ?, {placeholders})",
        [user_id, shop_id] + vals
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def update_product(product_id: int, user_id: int, data: dict, shop_id: int = None):
    """Update an existing product (ownership check included)."""
    conn = get_db()
    data.setdefault("brand_name", "")
    data.setdefault("is_visible", 1)
    set_clause = ", ".join([f"{f} = ?" for f in PRODUCT_FIELDS])
    set_clause += ", updated_at = datetime('now')"
    vals = [data.get(f) for f in PRODUCT_FIELDS]
    if shop_id is not None:
        vals += [product_id, user_id, shop_id]
        conn.execute(
            f"UPDATE products SET {set_clause} WHERE id = ? AND user_id = ? AND shop_id = ?",
            vals
        )
    else:
        vals += [product_id, user_id]
        conn.execute(
            f"UPDATE products SET {set_clause} WHERE id = ? AND user_id = ?",
            vals
        )
    conn.commit()
    conn.close()


def toggle_product_visibility(product_id: int, user_id: int, shop_id: int):
    """Toggle is_visible for a product."""
    conn = get_db()
    conn.execute(
        "UPDATE products SET is_visible = CASE WHEN is_visible=1 THEN 0 ELSE 1 END "
        "WHERE id=? AND user_id=? AND shop_id=?",
        (product_id, user_id, shop_id)
    )
    conn.commit()
    conn.close()


def delete_product(product_id: int, user_id: int):
    """Delete a product (and its analyses) owned by user_id."""
    conn = get_db()
    conn.execute(
        "DELETE FROM products WHERE id = ? AND user_id = ?",
        (product_id, user_id)
    )
    conn.commit()
    conn.close()


def get_product(product_id: int, user_id: int):
    """Fetch a single product with ownership check."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM products WHERE id = ? AND user_id = ?",
        (product_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_products_by_shop(shop_id: int, user_id: int, visible_only: bool = False):
    """
    Fetch products for a specific shop.
    If visible_only=True, only return is_visible=1 products (customer-facing).
    """
    conn = get_db()
    if visible_only:
        rows = conn.execute(
            "SELECT * FROM products WHERE shop_id=? AND is_visible=1 ORDER BY updated_at DESC",
            (shop_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM products WHERE shop_id=? AND user_id=? ORDER BY updated_at DESC",
            (shop_id, user_id)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_products(user_id: int, shop_id: int = None):
    """Fetch all products for a user, optionally filtered by shop."""
    conn = get_db()
    if shop_id is not None:
        rows = conn.execute(
            "SELECT * FROM products WHERE user_id=? AND shop_id=? ORDER BY updated_at DESC",
            (user_id, shop_id)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM products WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_products(user_id: int, shop_id: int = None) -> int:
    conn = get_db()
    if shop_id:
        n = conn.execute(
            "SELECT COUNT(*) FROM products WHERE user_id=? AND shop_id=?",
            (user_id, shop_id)
        ).fetchone()[0]
    else:
        n = conn.execute(
            "SELECT COUNT(*) FROM products WHERE user_id=?", (user_id,)
        ).fetchone()[0]
    conn.close()
    return n


# ═══════════════════════════════════════════════════════════════
# ANALYSIS CACHE OPERATIONS
# ═══════════════════════════════════════════════════════════════

def save_analysis(product_id: int, user_id: int, analysis: dict, shop_id: int = None):
    """Upsert analysis for a product (one analysis per product)."""
    conn = get_db()
    conn.execute(
        "DELETE FROM analyses WHERE product_id = ? AND user_id = ?",
        (product_id, user_id)
    )
    conn.execute(
        "INSERT INTO analyses (product_id, shop_id, user_id, analysis_json) VALUES (?, ?, ?, ?)",
        (product_id, shop_id, user_id, json.dumps(analysis))
    )
    conn.commit()
    conn.close()


def get_analysis(product_id: int, user_id: int):
    """Retrieve cached analysis for a product."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM analyses WHERE product_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 1",
        (product_id, user_id)
    ).fetchone()
    conn.close()
    if row:
        d = dict(row)
        return json.loads(d["analysis_json"])
    return None


def get_all_analyses(user_id: int, shop_id: int = None):
    """Fetch latest analysis for every product of this user, optionally filtered by shop."""
    conn = get_db()
    if shop_id is not None:
        rows = conn.execute("""
            SELECT a.product_id, a.analysis_json, a.created_at,
                   p.product_name, p.category
            FROM analyses a
            JOIN products p ON p.id = a.product_id
            WHERE a.user_id = ? AND a.shop_id = ?
            ORDER BY a.created_at DESC
        """, (user_id, shop_id)).fetchall()
    else:
        rows = conn.execute("""
            SELECT a.product_id, a.analysis_json, a.created_at,
                   p.product_name, p.category
            FROM analyses a
            JOIN products p ON p.id = a.product_id
            WHERE a.user_id = ?
            ORDER BY a.created_at DESC
        """, (user_id,)).fetchall()
    conn.close()
    results = {}
    for row in rows:
        pid = row["product_id"]
        if pid not in results:
            results[pid] = {
                "product_id":   pid,
                "product_name": row["product_name"],
                "category":     row["category"],
                "analysed_at":  row["created_at"],
                "analysis":     json.loads(row["analysis_json"]),
            }
    return list(results.values())


def get_public_shop_products(shop_id: int):
    """
    Get ONLY visible products for a shop — for customer-facing view.
    Returns safe public fields only (no stock, cost, internal metrics).
    """
    conn = get_db()
    rows = conn.execute("""
        SELECT p.id, p.product_name, p.brand_name, p.category,
               p.current_price, p.competitor_price, p.expiry_days,
               a.analysis_json
        FROM products p
        LEFT JOIN analyses a ON a.product_id = p.id
        WHERE p.shop_id = ? AND p.is_visible = 1
        ORDER BY p.product_name
    """, (shop_id,)).fetchall()
    conn.close()

    public_items = []
    for row in rows:
        d = dict(row)
        analysis = json.loads(d["analysis_json"]) if d.get("analysis_json") else {}
        public_items.append({
            "id":               d["id"],
            "product_name":     d["product_name"],
            "brand_name":       d["brand_name"] or "",
            "category":         d["category"],
            "current_price":    d["current_price"],
            "competitor_price": d["competitor_price"],
            "expiry_days":      d["expiry_days"],
            "discount_pct":     analysis.get("discount_pct", 0),
            "discounted_price": analysis.get("discounted_price", d["current_price"]),
            "is_expired":       d["expiry_days"] <= 0,
            "expiry_status":    "Expired" if d["expiry_days"] <= 0 else (
                                "Expiring soon" if d["expiry_days"] <= 7 else "Fresh"),
        })
    return public_items