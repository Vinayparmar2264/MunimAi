"""
shop.py — MerchAI v6 Legacy Multi-Product Shop Blueprint
- Fixed: Date serialization compatibility.
- Fixed: Safe string slicing for dates to prevent AttributeError.
"""

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from functools import wraps
from database import (add_product, update_product, delete_product,
                      get_product, get_all_products, get_all_analyses,
                      save_analysis, get_analysis, count_products)

shop_bp = Blueprint("shop", __name__, url_prefix="/shop")

CATEGORIES = ["Fashion", "Grocery", "Electronics", "FMCG", "Seasonal"]


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to access your shop.", "warning")
            return redirect(url_for("auth.login", next=request.url))
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
# DASHBOARD
# ═══════════════════════════════════════════════════════════════

@shop_bp.route("/dashboard")
@login_required
def dashboard():
    uid      = session["user_id"]
    products = get_all_products(uid)
    analyses = {a["product_id"]: a for a in get_all_analyses(uid)}

    for p in products:
        a = analyses.get(p["id"])
        if a:
            d = a["analysis"]
            p["_summary"] = {
                "health_score": d.get("health_score", "—"),
                "health_grade": d.get("health_grade", "—"),
                "order_action": d.get("order_action", "—"),
                "discount_pct": d.get("discount_pct", 0),
                "csat_score":   d.get("csat_score", "—"),
                # FIXED: String safety
                "analysed_at": str(a.get("analysed_at", ""))[:16],
            }
        else:
            p["_summary"] = None

    return render_template("dashboard/dashboard.html",
                           products=products,
                           product_count=len(products),
                           user_name=session.get("user_name", ""))


# ═══════════════════════════════════════════════════════════════
# ADD, EDIT, DELETE & ANALYSE ROUTES
# ═══════════════════════════════════════════════════════════════

@shop_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    if request.method == "POST":
        try:
            raw = _raw_from_form(request.form)
        except ValueError as e:
            flash(str(e), "danger")
            return render_template("dashboard/product_form.html",
                                   mode="add", categories=CATEGORIES,
                                   form_data=request.form)

        uid = session["user_id"]
        pid = add_product(uid, raw, shop_id=None)

        from app import analyse
        d = analyse(raw)
        save_analysis(pid, uid, d)
        session["raw_input"]       = raw
        session["analysis"]        = d
        session["shop_product_id"] = pid

        flash(f"✓ '{raw['product_name']}' added and analysed!", "success")
        return redirect(url_for("shop.forecast", product_id=pid))

    return render_template("dashboard/product_form.html",
                           mode="add", categories=CATEGORIES, form_data={})


@shop_bp.route("/edit/<int:product_id>", methods=["GET", "POST"])
@login_required
def edit(product_id):
    uid  = session["user_id"]
    prod = get_product(product_id, uid)
    if not prod:
        flash("Product not found.", "danger")
        return redirect(url_for("shop.dashboard"))

    if request.method == "POST":
        try:
            raw = _raw_from_form(request.form)
        except ValueError as e:
            flash(str(e), "danger")
            return render_template("dashboard/product_form.html",
                                   mode="edit", product_id=product_id,
                                   categories=CATEGORIES, form_data=request.form)

        update_product(product_id, uid, raw)
        from app import analyse
        d = analyse(raw)
        save_analysis(product_id, uid, d)
        session["raw_input"]       = raw
        session["analysis"]        = d
        session["shop_product_id"] = product_id

        flash(f"✓ '{raw['product_name']}' updated and re-analysed!", "success")
        return redirect(url_for("shop.forecast", product_id=product_id))

    return render_template("dashboard/product_form.html",
                           mode="edit", product_id=product_id,
                           categories=CATEGORIES, form_data=prod)


@shop_bp.route("/delete/<int:product_id>", methods=["POST"])
@login_required
def delete(product_id):
    uid  = session["user_id"]
    prod = get_product(product_id, uid)
    if prod:
        delete_product(product_id, uid)
        flash(f"'{prod['product_name']}' has been removed.", "info")
    else:
        flash("Product not found.", "danger")
    return redirect(url_for("shop.dashboard"))


@shop_bp.route("/analyse/<int:product_id>")
@login_required
def run_analysis(product_id):
    uid  = session["user_id"]
    prod = get_product(product_id, uid)
    if not prod:
        flash("Product not found.", "danger")
        return redirect(url_for("shop.dashboard"))

    raw = {k: prod[k] for k in [
        "product_name", "brand_name", "category",
        "sales_last_week", "sales_last_month",
        "stock", "expiry_days", "current_price", "cost_price",
        "competitor_price", "season_factor", "demand_variability",
        "lead_time_days", "holding_cost_pct", "order_cost",
        "target_service_level", "reorder_window_days",
    ] if k in prod}
    raw.setdefault("brand_name", "")

    from app import analyse
    d = analyse(raw)
    save_analysis(product_id, uid, d)

    session["raw_input"]       = raw
    session["analysis"]        = d
    session["shop_product_id"] = product_id

    flash(f"Analysis complete for '{prod['product_name']}'.", "success")
    return redirect(url_for("shop.forecast", product_id=product_id))


# ═══════════════════════════════════════════════════════════════
# PER-PRODUCT PAGES & SIMULATION
# ═══════════════════════════════════════════════════════════════

@shop_bp.route("/predict/<int:product_id>")
@login_required
def forecast(product_id):
    uid  = session["user_id"]
    prod = get_product(product_id, uid)
    if not prod:
        flash("Product not found.", "danger")
        return redirect(url_for("shop.dashboard"))
    d = get_analysis(product_id, uid)
    if not d:
        return redirect(url_for("shop.run_analysis", product_id=product_id))
    return render_template("predict.html", d=d,
                           product_name=prod["product_name"],
                           expiry_days=prod["expiry_days"],
                           shop_product_id=product_id)


@shop_bp.route("/decision/<int:product_id>")
@login_required
def decision(product_id):
    uid  = session["user_id"]
    prod = get_product(product_id, uid)
    if not prod:
        flash("Product not found.", "danger")
        return redirect(url_for("shop.dashboard"))
    d = get_analysis(product_id, uid)
    if not d:
        return redirect(url_for("shop.run_analysis", product_id=product_id))
    return render_template("decision.html", d=d,
                           product_name=prod["product_name"],
                           shop_product_id=product_id)


@shop_bp.route("/results/<int:product_id>")
@login_required
def results(product_id):
    uid  = session["user_id"]
    prod = get_product(product_id, uid)
    if not prod:
        flash("Product not found.", "danger")
        return redirect(url_for("shop.dashboard"))
    d = get_analysis(product_id, uid)
    if not d:
        return redirect(url_for("shop.run_analysis", product_id=product_id))
    return render_template("results.html", d=d,
                           product_name=prod["product_name"],
                           shop_product_id=product_id)


@shop_bp.route("/simulate/<int:product_id>", methods=["GET", "POST"])
@login_required
def simulate(product_id):
    uid  = session["user_id"]
    prod = get_product(product_id, uid)
    if not prod:
        flash("Product not found.", "danger")
        return redirect(url_for("shop.dashboard"))
    d = get_analysis(product_id, uid)
    if not d:
        return redirect(url_for("shop.run_analysis", product_id=product_id))

    import json as _json
    sim_results, sim_json = None, "[]"

    if request.method == "POST":
        try:
            from app import run_what_if
            bp, bs = d["current_price"], d["stock"]
            scenarios = [
                {"label": "Baseline (Current)",
                 "price": bp, "stock": bs, "season_factor": 1.0},
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

    return render_template("simulate.html", d=d,
                           product_name=prod["product_name"],
                           sim_results=sim_results,
                           sim_json=sim_json,
                           shop_product_id=product_id)


# ═══════════════════════════════════════════════════════════════
# FULL ANALYSIS TABLE
# ═══════════════════════════════════════════════════════════════

@shop_bp.route("/analysis-table")
@login_required
def analysis_table():
    uid      = session["user_id"]
    products = get_all_products(uid)
    analyses = {a["product_id"]: a for a in get_all_analyses(uid)}

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
                # FIXED: String safety
                "analysed_at":  str(a.get("analysed_at", ""))[:16],
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

    analysed      = [r for r in rows if not r.get("_not_analysed")]
    total_revenue  = sum(r.get("revenue_30d", 0) for r in analysed)
    total_profit   = sum(r.get("profit_30d",  0) for r in analysed)
    avg_health     = round(sum(r.get("health_score", 0) for r in analysed) /
                           max(len(analysed), 1), 1)
    urgent_count   = sum(1 for r in rows if r.get("order_urgency") in ("CRITICAL", "HIGH"))
    discount_count = sum(1 for r in rows if r.get("discount_pct", 0) > 0)

    return render_template("dashboard/analysis_table.html",
                           rows=rows, total_revenue=total_revenue,
                           total_profit=total_profit, avg_health=avg_health,
                           urgent_count=urgent_count, discount_count=discount_count,
                           product_count=len(products))
