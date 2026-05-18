"""
customer.py — MunimAI Customer Blueprint

Features:
- Customer dashboard
- Nearby shop discovery
- Shop browsing
- Public product viewing
- Product filtering
- Customer location management
- Distance calculation
- Multi-shop safe isolation
"""

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify
)

from functools import wraps

from database import (
    get_nearby_shops,
    get_shop,
    get_public_shop_products,
    update_user_location,
    _haversine
)

customer_bp = Blueprint(
    "customer",
    __name__,
    url_prefix="/customer"
)


# ============================================================
# LOGIN REQUIRED
# ============================================================

def login_required(f):

    @wraps(f)
    def wrapper(*args, **kwargs):

        if not session.get("user_id"):

            flash(
                "Please log in first.",
                "warning"
            )

            return redirect(
                url_for(
                    "auth.login",
                    next=request.url
                )
            )

        return f(*args, **kwargs)

    return wrapper


# ============================================================
# SESSION LOCATION
# ============================================================

def _get_session_location():

    lat = session.get("user_lat")
    lon = session.get("user_lon")

    if lat is not None and lon is not None:

        try:
            return float(lat), float(lon)

        except (TypeError, ValueError):
            pass

    return None, None


# ============================================================
# HOME / DASHBOARD
# ============================================================

@customer_bp.route("/", endpoint="home")
@login_required
def home():

    lat, lon = _get_session_location()

    try:
        radius = float(
            request.args.get("radius", 1.0)
        )

    except (TypeError, ValueError):
        radius = 1.0

    radius = max(0.1, min(radius, 50.0))

    search = request.args.get(
        "search",
        ""
    ).strip()

    category_filter = request.args.get(
        "category",
        ""
    ).strip()

    discount_filter = request.args.get(
        "min_discount",
        ""
    ).strip()

    shops = []

    # Nearby search
    if lat is not None and lon is not None:

        shops = get_nearby_shops(
            lat,
            lon,
            radius_km=radius,
            search_name=search
        )

    # Search by name
    elif search:

        shops = get_nearby_shops(
            0,
            0,
            radius_km=99999,
            search_name=search
        )

    # Enrich shop data
    for shop in shops:

        products = get_public_shop_products(
            shop["id"]
        )

        shop["product_count"] = len(products)

        shop["has_discounts"] = any(
            p.get("discount_pct", 0) > 0
            for p in products
        )

        shop["max_discount"] = max(
            (
                p.get("discount_pct", 0)
                for p in products
            ),
            default=0
        )

        shop["categories"] = list({
            p["category"]
            for p in products
        })

        # Discount filter
        if discount_filter:

            try:

                min_disc = float(discount_filter)

                if shop["max_discount"] < min_disc:
                    shop["_filtered"] = True

            except ValueError:
                pass

    shops = [
        s for s in shops
        if not s.get("_filtered")
    ]

    return render_template(

        "customer/nearby.html",

        shops=shops,

        user_lat=lat,
        user_lon=lon,

        user_loc_name=session.get(
            "user_loc_name",
            ""
        ),

        radius=radius,

        search=search,

        category_filter=category_filter,

        discount_filter=discount_filter,

        user_name=session.get(
            "user_name",
            ""
        )
    )


# Backward compatibility
@customer_bp.route("/dashboard", endpoint="dashboard")
@login_required
def dashboard():
    return home()


# ============================================================
# UPDATE LOCATION
# ============================================================

@customer_bp.route(
    "/update-location",
    methods=["POST"]
)

@login_required
def update_location():

    data = (
        request.get_json()
        if request.is_json
        else request.form
    )

    try:

        lat = float(
            data.get("latitude", 0)
        )

        lon = float(
            data.get("longitude", 0)
        )

        loc_name = str(
            data.get("location_name", "")
        ).strip()

    except (TypeError, ValueError):

        if request.is_json:

            return jsonify({
                "error": "Invalid coordinates"
            }), 400

        flash(
            "Invalid location.",
            "danger"
        )

        return redirect(
            url_for("customer.dashboard")
        )

    # Session
    session["user_lat"] = lat
    session["user_lon"] = lon
    session["user_loc_name"] = loc_name

    # Database
    uid = session.get("user_id")

    if uid:

        update_user_location(
            uid,
            lat,
            lon,
            loc_name
        )

    if request.is_json:

        return jsonify({
            "success": True,
            "lat": lat,
            "lon": lon,
            "name": loc_name
        })

    flash(
        "Location updated successfully.",
        "success"
    )

    return redirect(
        url_for("customer.dashboard")
    )


# ============================================================
# VIEW SHOP
# ============================================================

@customer_bp.route(
    "/shops/<int:shop_id>",
    endpoint="shop_detail"
)

@login_required
def view_shop(shop_id):

    shop = get_shop(shop_id)

    if not shop:

        flash(
            "Shop not found.",
            "danger"
        )

        return redirect(
            url_for("customer.dashboard")
        )

    products = get_public_shop_products(
        shop_id
    )

    # Filters
    category_filter = request.args.get(
        "category",
        ""
    ).strip()

    min_discount = request.args.get(
        "min_discount",
        ""
    ).strip()

    max_expiry = request.args.get(
        "max_expiry",
        ""
    ).strip()

    search_product = request.args.get(
        "product_search",
        ""
    ).strip()

    # Category filter
    if category_filter:

        products = [

            p for p in products

            if p["category"] == category_filter
        ]

    # Discount filter
    if min_discount:

        try:

            md = float(min_discount)

            products = [

                p for p in products

                if p.get("discount_pct", 0) >= md
            ]

        except ValueError:
            pass

    # Expiry filter
    if max_expiry:

        try:

            me = int(max_expiry)

            products = [

                p for p in products

                if p.get("expiry_days", 9999) <= me
            ]

        except ValueError:
            pass

    # Product search
    if search_product:

        sl = search_product.lower()

        products = [

            p for p in products

            if (
                sl in p["product_name"].lower()
                or
                sl in (
                    p.get("brand_name") or ""
                ).lower()
            )
        ]

    # Categories
    all_products = get_public_shop_products(
        shop_id
    )

    all_categories = sorted({

        p["category"]

        for p in all_products
    })

    # Distance
    lat, lon = _get_session_location()

    distance_km = None

    if (
        lat is not None
        and lon is not None
        and shop.get("latitude") is not None
        and shop.get("longitude") is not None
    ):

        distance_km = round(

            _haversine(
                lat,
                lon,
                shop["latitude"],
                shop["longitude"]
            ),

            2
        )

    # Save viewed shop
    session["viewing_shop_id"] = shop_id

    return render_template(

        "customer/shop_view.html",

        shop=shop,

        products=products,

        all_categories=all_categories,

        category_filter=category_filter,

        min_discount=min_discount,

        max_expiry=max_expiry,

        search_product=search_product,

        distance_km=distance_km,

        user_name=session.get(
            "user_name",
            ""
        )
    )


# ============================================================
# BROWSE SHOPS
# ============================================================

@customer_bp.route(
    "/shops",
    endpoint="shops"
)

@login_required
def browse_shops():

    search = request.args.get(
        "search",
        ""
    ).strip()

    lat, lon = _get_session_location()

    try:

        radius = float(
            request.args.get("radius", 50.0)
        )

    except (TypeError, ValueError):

        radius = 50.0

    if lat is not None and lon is not None:

        shops = get_nearby_shops(
            lat,
            lon,
            radius_km=radius,
            search_name=search
        )

    else:

        shops = get_nearby_shops(
            0,
            0,
            radius_km=99999,
            search_name=search
        )

    # Enrich shops
    for shop in shops:

        products = get_public_shop_products(
            shop["id"]
        )

        shop["product_count"] = len(products)

        shop["has_discounts"] = any(
            p.get("discount_pct", 0) > 0
            for p in products
        )

        shop["max_discount"] = max(
            (
                p.get("discount_pct", 0)
                for p in products
            ),
            default=0
        )

    return render_template(

        "customer/nearby.html",

        shops=shops,

        user_lat=lat,
        user_lon=lon,

        user_loc_name=session.get(
            "user_loc_name",
            ""
        ),

        radius=radius,

        search=search,

        category_filter="",

        discount_filter="",

        user_name=session.get(
            "user_name",
            ""
        ),

        browse_mode=True
    )
