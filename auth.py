"""
auth.py — MerchAI v6 Authentication Blueprint
Handles: /auth/login  /auth/signup  /auth/logout
         /auth/customer-signup  (customer registration with location)

Roles:
  shopkeeper — manages shops and products
  customer   — browses shops and uses chatbot
"""

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash)
from werkzeug.security import generate_password_hash, check_password_hash
import re
from database import create_user, get_user_by_email, update_user_location

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def _valid_password(pw: str):
    if len(pw) < 6:
        return "Password must be at least 6 characters."
    return None


# ── SHOPKEEPER SIGN UP ──────────────────────────────────────────
@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")

        errors = []
        if not name:
            errors.append("Full name is required.")
        if not _valid_email(email):
            errors.append("Please enter a valid email address.")
        pw_err = _valid_password(password)
        if pw_err:
            errors.append(pw_err)
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            return render_template("auth/signup.html",
                                   errors=errors, name=name, email=email)

        pw_hash = generate_password_hash(password, method="pbkdf2:sha256")
        user, err = create_user(name, email, pw_hash, role="shopkeeper")

        if err:
            return render_template("auth/signup.html",
                                   errors=[err], name=name, email=email)

        session["user_id"]    = user["id"]
        session["user_name"]  = user["name"]
        session["user_email"] = user["email"]
        session["user_role"]  = user["role"]
        flash(f"Welcome to MunimAI, {user['name']}! Your account is ready.", "success")
        return redirect(url_for("shopkeeper.my_shops"))

    return render_template("auth/signup.html")


# ── CUSTOMER SIGN UP ────────────────────────────────────────────
@auth_bp.route("/customer-signup", methods=["GET", "POST"])
def customer_signup():
    if session.get("user_id"):
        return redirect(url_for("customer.home"))

    if request.method == "POST":
        name      = request.form.get("name", "").strip()
        email     = request.form.get("email", "").strip()
        password  = request.form.get("password", "")
        confirm   = request.form.get("confirm_password", "")
        latitude  = request.form.get("latitude", "").strip()
        longitude = request.form.get("longitude", "").strip()
        loc_name  = request.form.get("location_name", "").strip()

        errors = []
        if not name:
            errors.append("Full name is required.")
        if not _valid_email(email):
            errors.append("Please enter a valid email address.")
        pw_err = _valid_password(password)
        if pw_err:
            errors.append(pw_err)
        if password != confirm:
            errors.append("Passwords do not match.")

        lat = lon = None
        if latitude and longitude:
            try:
                lat = float(latitude)
                lon = float(longitude)
            except ValueError:
                errors.append("Invalid location coordinates.")

        if errors:
            return render_template("auth/customer_signup.html",
                                   errors=errors, name=name, email=email)

        pw_hash = generate_password_hash(password, method="pbkdf2:sha256")
        user, err = create_user(name, email, pw_hash, role="customer")

        if err:
            return render_template("auth/customer_signup.html",
                                   errors=[err], name=name, email=email)

        # Save location if provided
        if lat is not None and lon is not None:
            update_user_location(user["id"], lat, lon, loc_name)

        session["user_id"]       = user["id"]
        session["user_name"]     = user["name"]
        session["user_email"]    = user["email"]
        session["user_role"]     = "customer"
        session["user_lat"]      = lat
        session["user_lon"]      = lon
        session["user_loc_name"] = loc_name
        flash(f"Welcome, {user['name']}! Find shops near you.", "success")
        return redirect(url_for("customer.home"))

    return render_template("auth/customer_signup.html")


# ── UNIFIED LOG IN ──────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        role = session.get("user_role", "shopkeeper")
        return redirect(url_for("customer.home") if role == "customer"
                        else url_for("dashboard.index"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        remember = request.form.get("remember")

        if not email or not password:
            return render_template("auth/login.html",
                                   error="Please enter both email and password.",
                                   email=email)

        user = get_user_by_email(email)
        if not user or not check_password_hash(user["password_hash"], password):
            return render_template("auth/login.html",
                                   error="Incorrect email or password.",
                                   email=email)

        session.permanent = bool(remember)
        session["user_id"]    = user["id"]
        session["user_name"]  = user["name"]
        session["user_email"] = user["email"]
        session["user_role"]  = user.get("role", "shopkeeper")

        # Restore location for customers
        if user.get("latitude"):
            session["user_lat"]      = user["latitude"]
            session["user_lon"]      = user["longitude"]
            session["user_loc_name"] = user.get("location_name", "")

        flash(f"Welcome back, {user['name']}!", "success")
        next_page = request.args.get("next")
        if next_page:
            return redirect(next_page)
        role = user.get("role", "shopkeeper")
        return redirect(url_for("customer.home") if role == "customer"
                        else url_for("dashboard.index"))

    return render_template("auth/login.html")


# ── LOG OUT ─────────────────────────────────────────────────────
@auth_bp.route("/logout")
def logout():
    name = session.get("user_name", "")
    role = session.get("user_role", "shopkeeper")
    session.clear()
    flash(f"You've been logged out{', ' + name if name else ''}. See you soon!", "info")
    return redirect(url_for("auth.login"))
