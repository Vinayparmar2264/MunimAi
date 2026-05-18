"""
shopkeeper.py — MunimAI v6 Shopkeeper Blueprint
Multi-shop management: create/edit/delete shops, manage products per shop.

Routes:
  GET  /shopkeeper/shops              — list all my shops
  GET  /shopkeeper/shops/new          — new shop form
  POST /shopkeeper/shops/new          — create shop
  GET  /shopkeeper/shops/<id>/edit    — edit shop form
  POST /shopkeeper/shops/<id>/edit    — save shop edits
  POST /shopkeeper/shops/<id>/delete  — delete shop
  GET  /shopkeeper/shops/<id>/products            — products for one shop
  GET  /shopkeeper/shops/<id>/products/add        — add product form
  POST /shopkeeper/shops/<id>/products/add        — save new product
  GET  /shopkeeper/shops/<id>/products/<pid>/edit — edit product
  POST /shopkeeper/shops/<id>/products/<pid>/edit — save edits
  POST /shopkeeper/shops/<id>/products/<pid>/delete
  POST /shopkeeper/shops/<id>/products/<pid>/toggle-visibility
  GET  /shopkeeper/shops/<id>/products/<pid>/analyse
  GET  /shopkeeper/shops/<id>/table   — full analysis table for this shop
"""

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from functools import wraps
from database import (
    create_shop, get_shops_by_owner, get_shop, update_shop, delete_shop,
    add_product, update_product, delete_product, get_product,
    get_products_by_shop, get_all_analyses, save_analysis, get_analysis,
    toggle_product_visibility, count_products,
)

shopkeeper_bp = Blueprint("shopkeeper", __name__, url_prefix="/shopkeeper")
CATEGORIES = ["Fashion", "Grocery", "Electronics", "FMCG", "Seasonal"]


# ── Guards ──────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return wrapper


def shopkeeper_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        if session.get("user_role") not in ("shopkeeper", "admin"):
            flash("This area is for shopkeepers only.", "danger")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return wrapper


def _raw_from_form(form):
    """Parse and validate product form → raw dict or raise ValueError."""
    raw = {
        "product_name":         form.get("product_name", "").strip(),
        "brand_name":           form.get("brand_name", "").strip(),
        "category":             form.get("category", "FMCG"),
        "sales_last_week":      float(form.get("sales_last_week", 0)),
        "sales_last_month":     float(form.get("sales_last_month", 0)),
        "stock":                float(form.get("stock", 0)),
        "expiry_days":          int(form.get("expiry_days", 30)),
        "current_price":        float(form.get("current_price", 0)),
        "cost_price":           float(form.get("cost_price", 0)),
        "competitor_price":     float(form.get("competitor_price", 0) or 0),
        "season_factor":        float(form.get("season_factor", 1.0)),
        "demand_variability":   form.get("demand_variability", "Medium"),
        "lead_time_days":       int(form.get("lead_time_days", 3)),
        "holding_cost_pct":     float(form.get("holding_cost_pct", 25)),
        "order_cost":           float(form.get("order_cost", 500)),
        "target_service_level": int(form.get("target_service_level", 95)),
        "reorder_window_days":  int(form.get("reorder_window_days", 7)),
        "is_visible":           int(form.get("is_visible", 1)),
    }
    errors = []
    if not raw["product_name"]:
        errors.append("Product name is required.")
    if raw["cost_price"] >= raw["current_price"]:
        errors.append("Cost price must be less than selling price.")
    if raw["stock"] < 0:
        errors.append("Stock cannot be negative.")
    if errors:
        raise ValueError(" | ".join(errors))
    return raw


# ═══════════════════════════════════════════════════════════════
# SHOP MANAGEMENT
# ═══════════════════════════════════════════════════════════════

@shopkeeper_bp.route("/shops")
@shopkeeper_required
def my_shops():
    uid   = session["user_id"]
    shops = get_shops_by_owner(uid)

    # Attach product count to each shop
    for s in shops:
        s["product_count"] = count_products(uid, shop_id=s["id"])

    return render_template("shopkeeper/my_shops.html",
                           shops=shops, user_name=session.get("user_name", ""))


@shopkeeper_bp.route("/shops/new", methods=["GET", "POST"])
@shopkeeper_required
def new_shop():
    if request.method == "POST":
        shop_name     = request.form.get("shop_name", "").strip()
        shop_location = request.form.get("shop_location", "").strip()
        extra_notes   = request.form.get("extra_notes", "").strip()
        lat_str       = request.form.get("latitude", "").strip()
        lon_str       = request.form.get("longitude", "").strip()

        errors = []
        if not shop_name:
            errors.append("Shop name is required.")
        if not shop_location:
            errors.append("Shop location is required.")

        lat = lon = None
        if lat_str and lon_str:
            try:
                lat = float(lat_str)
                lon = float(lon_str)
            except ValueError:
                errors.append("Invalid coordinates — please use the map pin or enter manually.")

        if errors:
            return render_template("shopkeeper/shop_form.html",
                                   mode="new", errors=errors,
                                   form_data=request.form)

        uid = session["user_id"]
        sid = create_shop(uid, shop_name, shop_location, lat, lon, extra_notes)
        flash(f"✓ Shop '{shop_name}' created successfully!", "success")
        return redirect(url_for("shopkeeper.shop_products", shop_id=sid))

    return render_template("shopkeeper/shop_form.html", mode="new", form_data={})


@shopkeeper_bp.route("/shops/<int:shop_id>/edit", methods=["GET", "POST"])
@shopkeeper_required
def edit_shop(shop_id):
    uid  = session["user_id"]
    shop = get_shop(shop_id, uid)
    if not shop:
        flash("Shop not found.", "danger")
        return redirect(url_for("shopkeeper.my_shops"))

    if request.method == "POST":
        shop_name     = request.form.get("shop_name", "").strip()
        shop_location = request.form.get("shop_location", "").strip()
        extra_notes   = request.form.get("extra_notes", "").strip()
        lat_str       = request.form.get("latitude", "").strip()
        lon_str       = request.form.get("longitude", "").strip()

        errors = []
        if not shop_name:
            errors.append("Shop name is required.")
        if not shop_location:
            errors.append("Shop location is required.")

        lat = shop.get("latitude")
        lon = shop.get("longitude")
        if lat_str and lon_str:
            try:
                lat = float(lat_str)
                lon = float(lon_str)
            except ValueError:
                errors.append("Invalid coordinates.")

        if errors:
            return render_template("shopkeeper/shop_form.html",
                                   mode="edit", shop=shop, errors=errors,
                                   form_data=request.form)

        update_shop(shop_id, uid, shop_name, shop_location, lat, lon, extra_notes)
        flash(f"✓ Shop '{shop_name}' updated.", "success")
        return redirect(url_for("shopkeeper.my_shops"))

    return render_template("shopkeeper/shop_form.html",
                           mode="edit", shop=shop, form_data=shop)


@shopkeeper_bp.route("/shops/<int:shop_id>/delete", methods=["POST"])
@shopkeeper_required
def delete_shop_route(shop_id):
    uid  = session["user_id"]
    shop = get_shop(shop_id, uid)
    if shop:
        delete_shop(shop_id, uid)
        flash(f"Shop '{shop['shop_name']}' has been removed.", "info")
    else:
        flash("Shop not found.", "danger")
    return redirect(url_for("shopkeeper.my_shops"))


# ═══════════════════════════════════════════════════════════════
# PRODUCT MANAGEMENT (per shop)
# ═══════════════════════════════════════════════════════════════

@shopkeeper_bp.route("/shops/<int:shop_id>/products")
@shopkeeper_required
def shop_products(shop_id):
    uid  = session["user_id"]
    shop = get_shop(shop_id, uid)
    if not shop:
        flash("Shop not found.", "danger")
        return redirect(url_for("shopkeeper.my_shops"))

    products  = get_products_by_shop(shop_id, uid)
    analyses  = {a["product_id"]: a for a in get_all_analyses(uid, shop_id=shop_id)}

    for p in products:
        a = analyses.get(p["id"])
        if a:
            d = a["analysis"]
            p["_summary"] = {
                "health_score": d.get("health_score", "—"),
                "order_action": d.get("order_action", "—"),
                "discount_pct": d.get("discount_pct", 0),
                "csat_score":   d.get("csat_score", "—"),
                "analysed_at": (
                                a.get("analysed_at").strftime("%Y-%m-%d %H:%M")
                                if a.get("analysed_at")
                                else ""
                            ),
            }
        else:
            p["_summary"] = None

    return render_template("shopkeeper/shop_products.html",
                           shop=shop, products=products,
                           product_count=len(products),
                           user_name=session.get("user_name", ""))


@shopkeeper_bp.route("/shops/<int:shop_id>/products/add", methods=["GET", "POST"])
@shopkeeper_required
def add_product_to_shop(shop_id):
    uid  = session["user_id"]
    shop = get_shop(shop_id, uid)
    if not shop:
        flash("Shop not found.", "danger")
        return redirect(url_for("shopkeeper.my_shops"))

    if request.method == "POST":
        try:
            raw = _raw_from_form(request.form)
        except ValueError as e:
            flash(str(e), "danger")
            return render_template("shopkeeper/product_form.html",
                                   mode="add", shop=shop,
                                   categories=CATEGORIES, form_data=request.form)

        pid = add_product(uid, raw, shop_id=shop_id)

        # Run analysis immediately
        from app import analyse
        d = analyse(raw)
        save_analysis(pid, uid, d, shop_id=shop_id)

        flash(f"✓ '{raw['product_name']}' added to {shop['shop_name']}!", "success")
        return redirect(url_for("shopkeeper.shop_products", shop_id=shop_id))

    return render_template("shopkeeper/product_form.html",
                           mode="add", shop=shop,
                           categories=CATEGORIES, form_data={})


@shopkeeper_bp.route("/shops/<int:shop_id>/products/<int:product_id>/edit",
                     methods=["GET", "POST"])
@shopkeeper_required
def edit_product(shop_id, product_id):
    uid  = session["user_id"]
    shop = get_shop(shop_id, uid)
    prod = get_product(product_id, uid)
    if not shop or not prod:
        flash("Product not found.", "danger")
        return redirect(url_for("shopkeeper.my_shops"))

    if request.method == "POST":
        try:
            raw = _raw_from_form(request.form)
        except ValueError as e:
            flash(str(e), "danger")
            return render_template("shopkeeper/product_form.html",
                                   mode="edit", shop=shop,
                                   product_id=product_id,
                                   categories=CATEGORIES, form_data=request.form)

        update_product(product_id, uid, raw, shop_id=shop_id)
        from app import analyse
        d = analyse(raw)
        save_analysis(product_id, uid, d, shop_id=shop_id)
        flash(f"✓ '{raw['product_name']}' updated and re-analysed!", "success")
        return redirect(url_for("shopkeeper.shop_products", shop_id=shop_id))

    return render_template("shopkeeper/product_form.html",
                           mode="edit", shop=shop,
                           product_id=product_id,
                           categories=CATEGORIES, form_data=prod)


@shopkeeper_bp.route("/shops/<int:shop_id>/products/<int:product_id>/delete",
                     methods=["POST"])
@shopkeeper_required
def delete_product_route(shop_id, product_id):
    uid  = session["user_id"]
    prod = get_product(product_id, uid)
    if prod:
        delete_product(product_id, uid)
        flash(f"'{prod['product_name']}' removed.", "info")
    else:
        flash("Product not found.", "danger")
    return redirect(url_for("shopkeeper.shop_products", shop_id=shop_id))


@shopkeeper_bp.route("/shops/<int:shop_id>/products/<int:product_id>/toggle-visibility",
                     methods=["POST"])
@shopkeeper_required
def toggle_visibility(shop_id, product_id):
    uid  = session["user_id"]
    prod = get_product(product_id, uid)
    if prod:
        toggle_product_visibility(product_id, uid, shop_id)
        new_state = "visible" if prod["is_visible"] == 0 else "hidden"
        flash(f"'{prod['product_name']}' is now {new_state} to customers.", "info")
    else:
        flash("Product not found.", "danger")
    return redirect(url_for("shopkeeper.shop_products", shop_id=shop_id))


@shopkeeper_bp.route("/shops/<int:shop_id>/products/<int:product_id>/analyse")
@shopkeeper_required
def run_analysis(shop_id, product_id):
    uid  = session["user_id"]
    shop = get_shop(shop_id, uid)
    prod = get_product(product_id, uid)
    if not shop or not prod:
        flash("Product not found.", "danger")
        return redirect(url_for("shopkeeper.my_shops"))

    from app import analyse
    raw = {k: prod[k] for k in [
        "product_name", "brand_name", "category",
        "sales_last_week", "sales_last_month",
        "stock", "expiry_days", "current_price", "cost_price",
        "competitor_price", "season_factor", "demand_variability",
        "lead_time_days", "holding_cost_pct", "order_cost",
        "target_service_level", "reorder_window_days",
    ]}
    d = analyse(raw)
    save_analysis(product_id, uid, d, shop_id=shop_id)

    # Store in session for detail pages
    session["raw_input"]       = raw
    session["analysis"]        = d
    session["shop_product_id"] = product_id
    session["current_shop_id"] = shop_id

    flash(f"Analysis refreshed for '{prod['product_name']}'.", "success")
    return redirect(url_for("shopkeeper.product_forecast",
                            shop_id=shop_id, product_id=product_id))


# ── Per-product detail pages ────────────────────────────────────

@shopkeeper_bp.route("/shops/<int:shop_id>/products/<int:product_id>/forecast")
@shopkeeper_required
def product_forecast(shop_id, product_id):
    uid = session["user_id"]
    d, pname = _load_analysis(product_id, uid)
    if d is None:
        return redirect(url_for("shopkeeper.run_analysis",
                                shop_id=shop_id, product_id=product_id))
    shop = get_shop(shop_id, uid)
    return render_template("predict.html", d=d,
                           product_name=pname,
                           expiry_days=d["expiry_days"],
                           shop_product_id=product_id,
                           shop_id=shop_id,
                           shop=shop)


@shopkeeper_bp.route("/shops/<int:shop_id>/products/<int:product_id>/decision")
@shopkeeper_required
def product_decision(shop_id, product_id):
    uid = session["user_id"]
    d, pname = _load_analysis(product_id, uid)
    if d is None:
        return redirect(url_for("shopkeeper.run_analysis",
                                shop_id=shop_id, product_id=product_id))
    shop = get_shop(shop_id, uid)
    return render_template("decision.html", d=d,
                           product_name=pname,
                           shop_product_id=product_id,
                           shop_id=shop_id,
                           shop=shop)


@shopkeeper_bp.route("/shops/<int:shop_id>/products/<int:product_id>/results")
@shopkeeper_required
def product_results(shop_id, product_id):
    uid = session["user_id"]
    d, pname = _load_analysis(product_id, uid)
    if d is None:
        return redirect(url_for("shopkeeper.run_analysis",
                                shop_id=shop_id, product_id=product_id))
    shop = get_shop(shop_id, uid)
    return render_template("results.html", d=d,
                           product_name=pname,
                           shop_product_id=product_id,
                           shop_id=shop_id,
                           shop=shop)


@shopkeeper_bp.route("/shops/<int:shop_id>/products/<int:product_id>/simulate",
                     methods=["GET", "POST"])
@shopkeeper_required
def product_simulate(shop_id, product_id):
    uid  = session["user_id"]
    prod = get_product(product_id, uid)
    if not prod:
        flash("Product not found.", "danger")
        return redirect(url_for("shopkeeper.my_shops"))

    d = get_analysis(product_id, uid)
    if not d:
        return redirect(url_for("shopkeeper.run_analysis",
                                shop_id=shop_id, product_id=product_id))

    shop = get_shop(shop_id, uid)
    sim_results, sim_json = None, "[]"
    import json as _json

    if request.method == "POST":
        try:
            from app import run_what_if
            bp, bs = d["current_price"], d["stock"]
            scenarios = [
                {"label": "Baseline (Current)", "price": bp, "stock": bs, "season_factor": 1.0},
                {"label": request.form.get("s1_label", "Price Cut -10%"),
                 "price": float(request.form.get("s1_price", round(bp * 0.90, 2))),
                 "stock": float(request.form.get("s1_stock", bs)),
                 "season_factor": float(request.form.get("s1_season", 1.0))},
                {"label": request.form.get("s2_label", "Stock Up +50%"),
                 "price": float(request.form.get("s2_price", bp)),
                 "stock": float(request.form.get("s2_stock", round(bs * 1.5, 0))),
                 "season_factor": float(request.form.get("s2_season", 1.0))},
                {"label": request.form.get("s3_label", "Festival Season"),
                 "price": float(request.form.get("s3_price", bp)),
                 "stock": float(request.form.get("s3_stock", bs)),
                 "season_factor": float(request.form.get("s3_season", 1.5))},
            ]
            sim_results = run_what_if(d, scenarios)
            sim_json    = _json.dumps(sim_results)
        except Exception as e:
            flash(f"Simulation error: {e}", "danger")

    return render_template("simulate.html",
                           d=d,
                           product_name=prod["product_name"],
                           sim_results=sim_results,
                           sim_json=sim_json,
                           shop_product_id=product_id,
                           shop_id=shop_id,
                           shop=shop)


# ─── Full analysis table for one shop ──────────────────────────

@shopkeeper_bp.route("/shops/<int:shop_id>/table")
@shopkeeper_required
def shop_analysis_table(shop_id):
    uid  = session["user_id"]
    shop = get_shop(shop_id, uid)
    if not shop:
        flash("Shop not found.", "danger")
        return redirect(url_for("shopkeeper.my_shops"))

    products  = get_products_by_shop(shop_id, uid)
    analyses  = {a["product_id"]: a for a in get_all_analyses(uid, shop_id=shop_id)}

    rows = []
    for p in products:
        a = analyses.get(p["id"])
        if a:
            d = a["analysis"]
            rows.append({
                "id":           p["id"],
                "name":         p["product_name"],
                "brand_name":   p.get("brand_name", ""),
                "is_visible":   p.get("is_visible", 1),
                "category":     p["category"],
                "stock":        p["stock"],
                "price":        p["current_price"],
                "health_score": d.get("health_score", 0),
                "health_grade": d.get("health_grade", "—"),
                "csat_score":   d.get("csat_score", 0),
                "csat_level":   d.get("csat_level", "—"),
                "order_action": d.get("order_action", "—"),
                "order_urgency":d.get("order_urgency", "NONE"),
                "order_qty":    d.get("window_reorder_qty", 0),
                "window_days":  d.get("reorder_window_days", 7),
                "discount_pct": d.get("discount_pct", 0),
                "discount_tier":d.get("discount_tier", "NONE"),
                "profit_30d":   d.get("projected_profit_30d", 0),
                "revenue_30d":  d.get("projected_revenue_30d", 0),
                "zone_label":   d.get("zone_label", "—"),
                "zone_color":   d.get("zone_color", "success"),
                "days_to_sell": d.get("days_to_sell", 0),
                "analysed_at": (
                    a.get("analysed_at").strftime("%Y-%m-%d %H:%M")
                    if a.get("analysed_at")
                    else ""
                ),
                "confidence":   d.get("confidence_pct", 0),
            })
        else:
            rows.append({
                "id": p["id"], "name": p["product_name"],
                "brand_name": p.get("brand_name", ""),
                "is_visible": p.get("is_visible", 1),
                "category": p["category"], "stock": p["stock"],
                "price": p["current_price"],
                "_not_analysed": True,
            })

    urgency_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "NONE": 3, "LOW": 4}
    rows.sort(key=lambda r: urgency_order.get(r.get("order_urgency", "NONE"), 5))

    total_revenue  = sum(r.get("revenue_30d", 0) for r in rows if not r.get("_not_analysed"))
    total_profit   = sum(r.get("profit_30d",  0) for r in rows if not r.get("_not_analysed"))
    analysed_rows  = [r for r in rows if not r.get("_not_analysed")]
    avg_health     = round(sum(r.get("health_score", 0) for r in analysed_rows) /
                           max(len(analysed_rows), 1), 1)
    urgent_count   = sum(1 for r in rows if r.get("order_urgency") in ("CRITICAL", "HIGH"))
    discount_count = sum(1 for r in rows if r.get("discount_pct", 0) > 0)

    return render_template("shopkeeper/shop_analysis_table.html",
                           shop=shop,
                           rows=rows,
                           total_revenue=total_revenue,
                           total_profit=total_profit,
                           avg_health=avg_health,
                           urgent_count=urgent_count,
                           discount_count=discount_count,
                           product_count=len(products))


# ── Helpers ──────────────────────────────────────────────────────

def _load_analysis(product_id, uid):
    prod = get_product(product_id, uid)
    if not prod:
        return None, None
    d = get_analysis(product_id, uid)
    return d, prod["product_name"]
