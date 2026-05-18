"""
database.py — MunimAI PostgreSQL/Supabase Database Layer

FINAL STABLE VERSION
- PostgreSQL / Supabase compatible
- Multi-shop support
- Customer support
- Product analysis support
- Public product browsing
- Safe distance calculations
- Render compatible
"""

import os
import json
import psycopg2
import psycopg2.extras

from math import radians, sin, cos, sqrt, atan2


# ============================================================
# DATABASE URL
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL")


# ============================================================
# CONNECTION
# ============================================================

def get_db():

    if not DATABASE_URL:
        raise Exception(
            "DATABASE_URL environment variable missing."
        )

    return psycopg2.connect(DATABASE_URL)


def dict_cursor(conn):

    return conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )


# ============================================================
# INIT DATABASE
# ============================================================

def init_db():

    conn = get_db()
    cur = conn.cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (

        id SERIAL PRIMARY KEY,

        name TEXT NOT NULL,

        email TEXT UNIQUE NOT NULL,

        password_hash TEXT NOT NULL,

        role TEXT NOT NULL DEFAULT 'shopkeeper',

        latitude DOUBLE PRECISION,

        longitude DOUBLE PRECISION,

        location_name TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # SHOPS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS shops (

        id SERIAL PRIMARY KEY,

        owner_id INTEGER
            REFERENCES users(id)
            ON DELETE CASCADE,

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

        user_id INTEGER
            REFERENCES users(id)
            ON DELETE CASCADE,

        shop_id INTEGER
            REFERENCES shops(id)
            ON DELETE CASCADE,

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

        product_id INTEGER
            REFERENCES products(id)
            ON DELETE CASCADE,

        user_id INTEGER
            REFERENCES users(id)
            ON DELETE CASCADE,

        shop_id INTEGER
            REFERENCES shops(id)
            ON DELETE CASCADE,

        analysis_json TEXT NOT NULL,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()

    cur.close()
    conn.close()

    print(
        "[DB] PostgreSQL/Supabase initialized successfully"
    )


# ============================================================
# USER OPERATIONS
# ============================================================

def create_user(
        name,
        email,
        password_hash,
        role="shopkeeper"
):

    conn = get_db()
    cur = dict_cursor(conn)

    try:

        cur.execute("""
            INSERT INTO users
            (
                name,
                email,
                password_hash,
                role
            )
            VALUES (%s, %s, %s, %s)
            RETURNING *
        """, (
            name.strip(),
            email.strip().lower(),
            password_hash,
            role
        ))

        user = cur.fetchone()

        conn.commit()

        return dict(user), None

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

    conn = get_db()
    cur = dict_cursor(conn)

    cur.execute("""
        SELECT *
        FROM users
        WHERE email=%s
    """, (
        email.strip().lower(),
    ))

    row = cur.fetchone()

    cur.close()
    conn.close()

    return dict(row) if row else None


def get_user_by_id(user_id):

    conn = get_db()
    cur = dict_cursor(conn)

    cur.execute("""
        SELECT *
        FROM users
        WHERE id=%s
    """, (
        user_id,
    ))

    row = cur.fetchone()

    cur.close()
    conn.close()

    return dict(row) if row else None


def update_user_location(
        user_id,
        latitude,
        longitude,
        location_name=""
):

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

def create_shop(
        owner_id,
        shop_name,
        shop_location,
        latitude=None,
        longitude=None,
        extra_notes=""
):

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
    """, (
        owner_id,
    ))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [dict(r) for r in rows]


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
        """, (
            shop_id,
            owner_id
        ))

    else:

        cur.execute("""
            SELECT *
            FROM shops
            WHERE id=%s
            AND is_active=1
        """, (
            shop_id,
        ))

    row = cur.fetchone()

    cur.close()
    conn.close()

    return dict(row) if row else None


def update_shop(
        shop_id,
        owner_id,
        shop_name,
        shop_location,
        latitude=None,
        longitude=None,
        extra_notes=""
):

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

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a)
    )

    return R * c


def get_nearby_shops(
        lat,
        lon,
        radius_km=1.0,
        search_name=""
):

    conn = get_db()
    cur = dict_cursor(conn)

    if search_name:

        cur.execute("""
            SELECT *
            FROM shops
            WHERE is_active=1
            AND shop_name ILIKE %s
        """, (
            f"%{search_name}%",
        ))

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

        d = dict(row)

        if (
            d.get("latitude") is not None
            and
            d.get("longitude") is not None
        ):

            try:

                dist = _haversine(

                    float(lat),
                    float(lon),

                    float(d["latitude"]),
                    float(d["longitude"])
                )

            except Exception as e:

                print(
                    "DISTANCE ERROR:",
                    str(e)
                )

                continue

            if search_name or dist <= radius_km:

                d["distance_km"] = round(dist, 2)

                result.append(d)

        elif search_name:

            d["distance_km"] = None

            result.append(d)

    result.sort(
        key=lambda x:
        x["distance_km"]
        if x["distance_km"] is not None
        else 9999
    )

    return result


# ============================================================
# PUBLIC PRODUCTS
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
    """, (
        shop_id,
    ))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    public_items = []

    for row in rows:

        d = dict(row)

        analysis = (
            json.loads(d["analysis_json"])
            if d.get("analysis_json")
            else {}
        )

        public_items.append({

            "id": d["id"],

            "product_name": d["product_name"],

            "brand_name": d["brand_name"] or "",

            "category": d["category"],

            "current_price": d["current_price"],

            "competitor_price": d["competitor_price"],

            "expiry_days": d["expiry_days"],

            "discount_pct": analysis.get(
                "discount_pct",
                0
            ),

            "discounted_price": analysis.get(
                "discounted_price",
                d["current_price"]
            ),

            "is_expired":
                d["expiry_days"] <= 0,

            "expiry_status":
                "Expired"
                if d["expiry_days"] <= 0
                else (
                    "Expiring soon"
                    if d["expiry_days"] <= 7
                    else "Fresh"
                )
        })

    return public_items
