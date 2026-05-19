"""
database.py — MunimAI PostgreSQL/Supabase Database Layer

FINAL STABLE VERSION
- PostgreSQL / Supabase compatible
- Keeps existing helper names used by current blueprints
- Multi-shop support
- Customer support
- Product analysis support
- Public product browsing
- Safe distance calculations
- Render compatible
- Updated: Composite Unique Constraint for Multi-Role Auth (Shopkeeper + Customer)
"""

import os
import json
from datetime import datetime, date

import psycopg2
import psycopg2.extras

from math import radians, sin, cos, sqrt, atan2


# ============================================================
# DATABASE URL
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL")


# ============================================================
# CONNECTION HELPERS
# ============================================================

def _normalize_db_url(url: str) -> str:
    """
    Normalize common PostgreSQL connection URL variants.
    - postgres:// -> postgresql://
    - add sslmode=require for Supabase if missing
    """
    if not url:
        return url

    db_url = url.strip()

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    # Supabase often requires SSL.
    # If sslmode is missing, add it.
    if "supabase.co" in db_url and "sslmode=" not in db_url:
        joiner = "&" if "?" in db_url else "?"
        db_url = f"{db_url}{joiner}sslmode=require"

    return db_url


def get_db():
    """
    Return a new PostgreSQL connection.
    """
    if not DATABASE_URL:
        raise Exception("DATABASE_URL environment variable missing.")

    db_url = _normalize_db_url(DATABASE_URL)
    return psycopg2.connect(db_url, connect_timeout=10)


def dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


# ============================================================
# SERIALIZATION HELPERS
# ============================================================

def _serialize_value(value):
    """
    Convert datetime/date objects to strings so old code paths
    that slice / serialize values do not break.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _row_to_dict(row):
    if row is None:
        return None

    if isinstance(row, dict):
        out = dict(row)
    else:
        out = dict(row)

    for k, v in list(out.items()):
        out[k] = _serialize_value(v)

    return out


def _rows_to_dicts(rows):
    return [_row_to_dict(r) for r in rows]


# ============================================================
# SCHEMA HELPERS
# ============================================================

def _ensure_columns(cur, table_name, columns):
    """
    Add missing columns safely on existing PostgreSQL databases.
    columns = {column_name: column_ddl}
    """
    for col_name, col_ddl in columns.items():
        cur.execute(
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col_name} {col_ddl}"
        )


# ============================================================
# INIT DATABASE
# ============================================================

def init_db():
    conn = get_db()
    cur = conn.cursor()

    # USERS - Configured with composite unique constraint (email, role)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'shopkeeper',
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        location_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT users_email_role_key UNIQUE (email, role)
    );
    """)

    # SHOPS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS shops (
        id SERIAL PRIMARY KEY,
        owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        shop_name TEXT NOT NULL,
        shop_location TEXT NOT NULL,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        extra_notes TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # PRODUCTS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        shop_id INTEGER REFERENCES shops(id) ON DELETE CASCADE,
        product_name TEXT NOT NULL,
        brand_name TEXT DEFAULT '',
        category TEXT NOT NULL,
        sales_last_week DOUBLE PRECISION NOT NULL,
        sales_last_month DOUBLE PRECISION NOT NULL,
        stock DOUBLE PRECISION NOT NULL,
        expiry_days INTEGER NOT NULL,
        current_price DOUBLE PRECISION NOT NULL,
        cost_price DOUBLE PRECISION NOT NULL,
        competitor_price DOUBLE PRECISION DEFAULT 0,
        season_factor DOUBLE PRECISION DEFAULT 1.0,
        demand_variability TEXT DEFAULT 'Medium',
        lead_time_days INTEGER DEFAULT 3,
        holding_cost_pct DOUBLE PRECISION DEFAULT 25,
        order_cost DOUBLE PRECISION DEFAULT 500,
        target_service_level INTEGER DEFAULT 95,
        reorder_window_days INTEGER DEFAULT 7,
        is_visible INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # ANALYSES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS analyses (
        id SERIAL PRIMARY KEY,
        product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
        shop_id INTEGER REFERENCES shops(id) ON DELETE CASCADE,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        analysis_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Compatibility safety for existing databases
    _ensure_columns(cur, "users", {
        "role": "TEXT NOT NULL DEFAULT 'shopkeeper'",
        "latitude": "DOUBLE PRECISION",
        "longitude": "DOUBLE PRECISION",
        "location_name": "TEXT",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    _ensure_columns(cur, "shops", {
        "owner_id": "INTEGER",
        "shop_name": "TEXT",
        "shop_location": "TEXT",
        "latitude": "DOUBLE PRECISION",
        "longitude": "DOUBLE PRECISION",
        "extra_notes": "TEXT DEFAULT ''",
        "is_active": "INTEGER DEFAULT 1",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    _ensure_columns(cur, "products", {
        "user_id": "INTEGER",
        "shop_id": "INTEGER",
        "product_name": "TEXT",
        "brand_name": "TEXT DEFAULT ''",
        "category": "TEXT",
        "sales_last_week": "DOUBLE PRECISION",
        "sales_last_month": "DOUBLE PRECISION",
        "stock": "DOUBLE PRECISION",
        "expiry_days": "INTEGER",
        "current_price": "DOUBLE PRECISION",
        "cost_price": "DOUBLE PRECISION",
        "competitor_price": "DOUBLE PRECISION DEFAULT 0",
        "season_factor": "DOUBLE PRECISION DEFAULT 1.0",
        "demand_variability": "TEXT DEFAULT 'Medium'",
        "lead_time_days": "INTEGER DEFAULT 3",
        "holding_cost_pct": "DOUBLE PRECISION DEFAULT 25",
        "order_cost": "DOUBLE PRECISION DEFAULT 500",
        "target_service_level": "INTEGER DEFAULT 95",
        "reorder_window_days": "INTEGER DEFAULT 7",
        "is_visible": "INTEGER DEFAULT 1",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    _ensure_columns(cur, "analyses", {
        "product_id": "INTEGER",
        "shop_id": "INTEGER",
        "user_id": "INTEGER",
        "analysis_json": "TEXT",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    conn.commit()
    cur.close()
    conn.close()
    print("[DB] PostgreSQL/Supabase initialized successfully")


# ============================================================
# USER OPERATIONS
# ============================================================

def create_user(name, email, password_hash, role="shopkeeper"):
    conn = get_db()
    cur = dict_cursor(conn)

    try:
        cur.execute("""
            INSERT INTO users
            (name, email, password_hash, role)
            VALUES (%s, %s, %s, %s)
            RETURNING
                id, name, email, password_hash, role,
                latitude, longitude, location_name, created_at
        """, (
            name.strip(),
            email.strip().lower(),
            password_hash,
            role
        ))

        user = _row_to_dict(cur.fetchone())
        conn.commit()
        return user, None

    except Exception as e:
        conn.rollback()
        print("\n========== CREATE USER ERROR ==========")
        print(str(e))
        print("=======================================\n")
        return None, str(e)

    finally:
        cur.close()
        conn.close()


def get_user_by_email(email):
    """
    LEGACY HELPER: Kept to prevent breaking older legacy code paths.
    If multiple roles exist for one email, this returns the first matching ID.
    """
    conn = get_db()
    cur = dict_cursor(conn)

    cur.execute("""
        SELECT
            id, name, email, password_hash, role,
            latitude, longitude, location_name, created_at
        FROM users
        WHERE email=%s
        ORDER BY id ASC
        LIMIT 1
    """, (email.strip().lower(),))

    row = _row_to_dict(cur.fetchone())
    cur.close()
    conn.close()
    return row


def get_user_by_email_and_role(email, role):
    """
    NEW HELPER: Safely isolates authentication between Shopkeepers and Customers.
    Ensures role separation when the same email is shared.
    """
    conn = get_db()
    cur = dict_cursor(conn)

    cur.execute("""
        SELECT
            id, name, email, password_hash, role,
            latitude, longitude, location_name, created_at
        FROM users
        WHERE email=%s AND role=%s
    """, (email.strip().lower(), role))

    row = _row_to_dict(cur.fetchone())
    cur.close()
    conn.close()
    return row


def get_user_by_id(user_id):
    conn = get_db()
    cur = dict_cursor(conn)

    cur.execute("""
        SELECT
            id, name, email, password_hash, role,
            latitude, longitude, location_name, created_at
        FROM users
        WHERE id=%s
    """, (user_id,))

    row = _row_to_dict(cur.fetchone())
    cur.close()
    conn.close()
    return row


def update_user_location(user_id, latitude, longitude, location_name=""):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE users
        SET latitude=%s,
            longitude=%s,
            location_name=%s
        WHERE id=%s
    """, (
        latitude,
        longitude,
        location_name,
        user_id
    ))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# SHOP OPERATIONS
# ============================================================

def create_shop(owner_id, shop_name, shop_location, latitude=None, longitude=None, extra_notes=""):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO shops
        (
            owner_id,
            shop_name,
            shop_location,
            latitude,
            longitude,
            extra_notes
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        owner_id,
        shop_name.strip(),
        shop_location.strip(),
        latitude,
        longitude,
        extra_notes.strip()
    ))

    shop_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return shop_id


def get_shops_by_owner(owner_id):
    conn = get_db()
    cur = dict_cursor(conn)

    cur.execute("""
        SELECT *
        FROM shops
        WHERE owner_id=%s
        AND is_active=1
        ORDER BY created_at DESC
    """, (owner_id,))

    rows = _rows_to_dicts(cur.fetchall())
    cur.close()
    conn.close()
    return rows


def get_shop(shop_id, owner_id=None):
    conn = get_db()
    cur = dict_cursor(conn)

    if owner_id is not None:
        cur.execute("""
            SELECT *
            FROM shops
            WHERE id=%s
            AND owner_id=%s
            AND is_active=1
        """, (shop_id, owner_id))
    else:
        cur.execute("""
            SELECT *
            FROM shops
            WHERE id=%s
            AND is_active=1
        """, (shop_id,))

    row = _row_to_dict(cur.fetchone())
    cur.close()
    conn.close()
    return row


def update_shop(shop_id, owner_id, shop_name, shop_location, latitude=None, longitude=None, extra_notes=""):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE shops
        SET
            shop_name=%s,
            shop_location=%s,
            latitude=%s,
            longitude=%s,
            extra_notes=%s,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
        AND owner_id=%s
    """, (
        shop_name,
        shop_location,
        latitude,
        longitude,
        extra_notes,
        shop_id,
        owner_id
    ))

    conn.commit()
    cur.close()
    conn.close()


def delete_shop(shop_id, owner_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE shops
        SET is_active=0
        WHERE id=%s
        AND owner_id=%s
    """, (
        shop_id,
        owner_id
    ))

    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# DISTANCE
# ============================================================

def _haversine(lat1, lon1, lat2, lon2):
    R = 6371

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def get_nearby_shops(lat, lon, radius_km=1.0, search_name=""):
    conn = get_db()
    cur = dict_cursor(conn)

    if search_name:
        cur.execute("""
            SELECT *
            FROM shops
            WHERE is_active=1
            AND shop_name ILIKE %s
        """, (f"%{search_name}%",))
    else:
        cur.execute("""
            SELECT *
            FROM shops
            WHERE is_active=1
            AND latitude IS NOT NULL
            AND longitude IS NOT NULL
        """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = []

    for row in rows:
        d = _row_to_dict(row)

        if d.get("latitude") is not None and d.get("longitude") is not None:
            try:
                dist = _haversine(
                    float(lat),
                    float(lon),
                    float(d["latitude"]),
                    float(d["longitude"])
                )
            except Exception as e:
                print("DISTANCE ERROR:", str(e))
                continue

            if search_name or dist <= radius_km:
                d["distance_km"] = round(dist, 2)
                result.append(d)

        elif search_name:
            d["distance_km"] = None
            result.append(d)

    result.sort(
        key=lambda x: x["distance_km"] if x["distance_km"] is not None else 9999
    )
    return result


# ============================================================
# PRODUCT OPERATIONS
# ============================================================

PRODUCT_FIELDS = [
    "product_name",
    "brand_name",
    "category",
    "sales_last_week",
    "sales_last_month",
    "stock",
    "expiry_days",
    "current_price",
    "cost_price",
    "competitor_price",
    "season_factor",
    "demand_variability",
    "lead_time_days",
    "holding_cost_pct",
    "order_cost",
    "target_service_level",
    "reorder_window_days",
    "is_visible",
]


def add_product(user_id, data, shop_id=None):
    conn = get_db()
    cur = conn.cursor()

    data.setdefault("brand_name", "")
    data.setdefault("is_visible", 1)

    vals = [data.get(f) for f in PRODUCT_FIELDS]
    placeholders = ", ".join(["%s"] * len(PRODUCT_FIELDS))
    cols = ", ".join(PRODUCT_FIELDS)

    cur.execute(
        f"""
        INSERT INTO products
        (
            user_id,
            shop_id,
            {cols}
        )
        VALUES
        (
            %s,
            %s,
            {placeholders}
        )
        RETURNING id
        """,
        [user_id, shop_id] + vals
    )

    pid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return pid


def update_product(product_id, user_id, data, shop_id=None):
    conn = get_db()
    cur = conn.cursor()

    data.setdefault("brand_name", "")
    data.setdefault("is_visible", 1)

    set_clause = ", ".join([f"{f}=%s" for f in PRODUCT_FIELDS])
    vals = [data.get(f) for f in PRODUCT_FIELDS]

    if shop_id is not None:
        vals += [product_id, user_id, shop_id]
        cur.execute(
            f"""
            UPDATE products
            SET {set_clause},
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            AND user_id=%s
            AND shop_id=%s
            """,
            vals
        )
    else:
        vals += [product_id, user_id]
        cur.execute(
            f"""
            UPDATE products
            SET {set_clause},
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            AND user_id=%s
            """,
            vals
        )

    conn.commit()
    cur.close()
    conn.close()


def delete_product(product_id, user_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM products
        WHERE id=%s
        AND user_id=%s
    """, (product_id, user_id))

    conn.commit()
    cur.close()
    conn.close()


def get_product(product_id, user_id):
    conn = get_db()
    cur = dict_cursor(conn)

    cur.execute("""
        SELECT *
        FROM products
        WHERE id=%s
        AND user_id=%s
    """, (product_id, user_id))

    row = _row_to_dict(cur.fetchone())
    cur.close()
    conn.close()
    return row


def get_products_by_shop(shop_id, user_id, visible_only=False):
    conn = get_db()
    cur = dict_cursor(conn)

    if visible_only:
        cur.execute("""
            SELECT *
            FROM products
            WHERE shop_id=%s
            AND is_visible=1
            ORDER BY updated_at DESC
        """, (shop_id,))
    else:
        cur.execute("""
            SELECT *
            FROM products
            WHERE shop_id=%s
            AND user_id=%s
            ORDER BY updated_at DESC
        """, (shop_id, user_id))

    rows = _rows_to_dicts(cur.fetchall())
    cur.close()
    conn.close()
    return rows


def get_all_products(user_id, shop_id=None):
    conn = get_db()
    cur = dict_cursor(conn)

    if shop_id is not None:
        cur.execute("""
            SELECT *
            FROM products
            WHERE user_id=%s
            AND shop_id=%s
            ORDER BY updated_at DESC
        """, (user_id, shop_id))
    else:
        cur.execute("""
            SELECT *
            FROM products
            WHERE user_id=%s
            ORDER BY updated_at DESC
        """, (user_id,))

    rows = _rows_to_dicts(cur.fetchall())
    cur.close()
    conn.close()
    return rows


def count_products(user_id, shop_id=None):
    conn = get_db()
    cur = conn.cursor()

    if shop_id is not None:
        cur.execute("""
            SELECT COUNT(*)
            FROM products
            WHERE user_id=%s
            AND shop_id=%s
        """, (user_id, shop_id))
    else:
        cur.execute("""
            SELECT COUNT(*)
            FROM products
            WHERE user_id=%s
        """, (user_id,))

    n = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n


def toggle_product_visibility(product_id, user_id, shop_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE products
        SET is_visible =
            CASE
                WHEN is_visible=1 THEN 0
                ELSE 1
            END
        WHERE id=%s
        AND user_id=%s
        AND shop_id=%s
    """, (product_id, user_id, shop_id))

    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# ANALYSIS OPERATIONS
# ============================================================

def save_analysis(product_id, user_id, analysis, shop_id=None):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM analyses
        WHERE product_id=%s
        AND user_id=%s
    """, (product_id, user_id))

    cur.execute("""
        INSERT INTO analyses
        (
            product_id,
            shop_id,
            user_id,
            analysis_json
        )
        VALUES (%s, %s, %s, %s)
    """, (
        product_id,
        shop_id,
        user_id,
        json.dumps(analysis)
    ))

    conn.commit()
    cur.close()
    conn.close()


def get_analysis(product_id, user_id):
    conn = get_db()
    cur = dict_cursor(conn)

    cur.execute("""
        SELECT *
        FROM analyses
        WHERE product_id=%s
        AND user_id=%s
        ORDER BY created_at DESC
        LIMIT 1
    """, (product_id, user_id))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        d = _row_to_dict(row)
        try:
            return json.loads(d["analysis_json"])
        except Exception:
            return None

    return None


def get_all_analyses(user_id, shop_id=None):
    conn = get_db()
    cur = dict_cursor(conn)

    if shop_id is not None:
        cur.execute("""
            SELECT
                a.product_id,
                a.analysis_json,
                a.created_at,
                p.product_name,
                p.category
            FROM analyses a
            JOIN products p
            ON p.id = a.product_id
            WHERE a.user_id=%s
            AND a.shop_id=%s
            ORDER BY a.created_at DESC
        """, (user_id, shop_id))
    else:
        cur.execute("""
            SELECT
                a.product_id,
                a.analysis_json,
                a.created_at,
                p.product_name,
                p.category
            FROM analyses a
            JOIN products p
            ON p.id = a.product_id
            WHERE a.user_id=%s
            ORDER BY a.created_at DESC
        """, (user_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    results = {}

    for row in rows:
        pid = row["product_id"]

        if pid not in results:
            try:
                analysis = json.loads(row["analysis_json"])
            except Exception:
                analysis = {}

            results[pid] = {
                "product_id": pid,
                "product_name": row["product_name"],
                "category": row["category"],
                "analysed_at": _serialize_value(row["created_at"]),
                "analysis": analysis,
            }

    return list(results.values())


# ============================================================
# PUBLIC CUSTOMER PRODUCTS
# ============================================================

def get_public_shop_products(shop_id):
    conn = get_db()
    cur = dict_cursor(conn)

    cur.execute("""
        SELECT
            p.id,
            p.product_name,
            p.brand_name,
            p.category,
            p.current_price,
            p.competitor_price,
            p.expiry_days,
            a.analysis_json
        FROM products p
        LEFT JOIN analyses a
        ON a.product_id = p.id
        WHERE p.shop_id=%s
        AND p.is_visible=1
        ORDER BY p.product_name
    """, (shop_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    public_items = []

    for row in rows:
        d = _row_to_dict(row)

        try:
            analysis = json.loads(d["analysis_json"]) if d.get("analysis_json") else {}
        except Exception:
            analysis = {}

        expiry_days = d.get("expiry_days", 0) or 0
        current_price = d.get("current_price", 0) or 0
        competitor_price = d.get("competitor_price", 0) or 0

        public_items.append({
            "id": d["id"],
            "product_name": d["product_name"],
            "brand_name": d["brand_name"] or "",
            "category": d["category"],
            "current_price": current_price,
            "competitor_price": competitor_price,
            "expiry_days": expiry_days,
            "discount_pct": analysis.get("discount_pct", 0),
            "discounted_price": analysis.get("discounted_price", current_price),
            "is_expired": expiry_days <= 0,
            "expiry_status": (
                "Expired" if expiry_days <= 0
                else "Expiring soon" if expiry_days <= 7
                else "Fresh"
            ),
        })

    return public_items


# Backward-compatibility aliases used by some blueprints / old code
def get_public_shop_data(shop_id):
    return get_public_shop_products(shop_id)


def get_visible_products(shop_id):
    return get_public_shop_products(shop_id)
