"""
auth.py — MunimAI Authentication Blueprint

FINAL STABLE VERSION
- Customer signup/login
- Shopkeeper signup/login
- Session handling
- PostgreSQL/Supabase compatible
- Render compatible
- Preserves existing functionality
"""

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from database import (
    create_user,
    get_user_by_email,
    update_user_location
)

auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth"
)


# ============================================================
# LOGIN
# ============================================================

@auth_bp.route(
    "/login",
    methods=["GET", "POST"]
)

def login():

    if request.method == "POST":

        print("\n========== LOGIN DEBUG ==========")
        print("FORM:", dict(request.form))

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        errors = []

        if not email:
            errors.append("Email is required.")

        if not password:
            errors.append("Password is required.")

        user = None

        if not errors:

            user = get_user_by_email(email)

            print("USER FOUND:", user)

            if not user:

                errors.append(
                    "Invalid email or password."
                )

            else:

                if not check_password_hash(
                    user["password_hash"],
                    password
                ):

                    errors.append(
                        "Invalid email or password."
                    )

        if not errors and user:

            session.clear()

            # Session data
            session["user_id"] = user["id"]

            session["user_name"] = user["name"]

            session["user_email"] = user["email"]

            session["role"] = user["role"]

            # Compatibility
            session["user_role"] = user["role"]

            # Customer location
            if user.get("latitude") is not None:

                session["user_lat"] = (
                    user.get("latitude")
                )

                session["user_lon"] = (
                    user.get("longitude")
                )

                session["user_loc_name"] = (
                    user.get("location_name") or ""
                )

            print("LOGIN SUCCESS")

            # Redirect logic
            next_url = request.args.get("next")

            if next_url:
                return redirect(next_url)

            # Customer
            if user["role"] == "customer":

                return redirect(
                    url_for("customer.dashboard")
                )

            # Shopkeeper
            return redirect(
                url_for("shopkeeper.dashboard")
            )

        print("LOGIN ERRORS:", errors)

        for e in errors:
            flash(e, "danger")

    return render_template(
        "auth/login.html"
    )


# ============================================================
# SHOPKEEPER SIGNUP
# ============================================================

@auth_bp.route(
    "/signup",
    methods=["GET", "POST"]
)

def signup():

    if request.method == "POST":

        print("\n========== SHOPKEEPER SIGNUP ==========")
        print("FORM:", dict(request.form))

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        errors = []

        # Validation
        if not name:
            errors.append("Name is required.")

        if not email:
            errors.append("Email is required.")

        if not password:
            errors.append("Password is required.")

        if len(password) < 6:

            errors.append(
                "Password must be at least 6 characters."
            )

        if password != confirm_password:

            errors.append(
                "Passwords do not match."
            )

        user = None

        if not errors:

            password_hash = generate_password_hash(
                password
            )

            print(
                "Creating shopkeeper account..."
            )

            user, error = create_user(

                name=name,

                email=email,

                password_hash=password_hash,

                role="shopkeeper"
            )

            print("USER:", user)
            print("ERROR:", error)

            if error:
                errors.append(error)

        if not errors and user:

            session.clear()

            session["user_id"] = user["id"]

            session["user_name"] = user["name"]

            session["user_email"] = user["email"]

            session["role"] = user["role"]

            # Compatibility
            session["user_role"] = user["role"]

            flash(
                "Shopkeeper account created successfully!",
                "success"
            )

            return redirect(
                url_for("shopkeeper.dashboard")
            )

        print("SHOPKEEPER ERRORS:", errors)

        for e in errors:
            flash(e, "danger")

    return render_template(
        "auth/signup.html"
    )


# ============================================================
# CUSTOMER SIGNUP
# ============================================================

@auth_bp.route(
    "/customer-signup",
    methods=["GET", "POST"]
)

def customer_signup():

    if request.method == "POST":

        print(
            "\n========== CUSTOMER SIGNUP DEBUG =========="
        )

        print(
            "FORM DATA:",
            dict(request.form)
        )

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        latitude = request.form.get(
            "latitude",
            ""
        )

        longitude = request.form.get(
            "longitude",
            ""
        )

        location_name = request.form.get(
            "location_name",
            ""
        ).strip()

        errors = []

        # ====================================================
        # VALIDATION
        # ====================================================

        if not name:
            errors.append("Name is required.")

        if not email:
            errors.append("Email is required.")

        if not password:
            errors.append("Password is required.")

        if len(password) < 6:

            errors.append(
                "Password must be at least 6 characters."
            )

        if password != confirm_password:

            errors.append(
                "Passwords do not match."
            )

        # ====================================================
        # LOCATION PARSING
        # ====================================================

        lat = None
        lon = None

        if (
            str(latitude).strip() != ""
            and
            str(longitude).strip() != ""
        ):

            try:

                lat = float(latitude)

                lon = float(longitude)

            except (TypeError, ValueError):

                errors.append(
                    "Invalid location coordinates."
                )

        # ====================================================
        # CREATE USER
        # ====================================================

        user = None

        if not errors:

            password_hash = generate_password_hash(
                password
            )

            print(
                "Creating customer account..."
            )

            user, error = create_user(

                name=name,

                email=email,

                password_hash=password_hash,

                role="customer"
            )

            print("USER:", user)
            print("ERROR:", error)

            if error:

                print(
                    "CUSTOMER SIGNUP ERROR:",
                    error
                )

                errors.append(error)

        # ====================================================
        # UPDATE LOCATION
        # ====================================================

        if not errors and user:

            try:

                if (
                    lat is not None
                    and
                    lon is not None
                ):

                    update_user_location(

                        user["id"],

                        lat,

                        lon,

                        location_name
                    )

                    print(
                        "Location updated successfully"
                    )

            except Exception as e:

                print(
                    "LOCATION UPDATE ERROR:",
                    str(e)
                )

        # ====================================================
        # LOGIN CUSTOMER
        # ====================================================

        if not errors and user:

            session.clear()

            session["user_id"] = user["id"]

            session["user_name"] = user["name"]

            session["user_email"] = user["email"]

            session["role"] = user["role"]

            # Compatibility
            session["user_role"] = user["role"]

            if (
                lat is not None
                and
                lon is not None
            ):

                session["user_lat"] = lat

                session["user_lon"] = lon

                session["user_loc_name"] = (
                    location_name
                )

            flash(
                "Customer account created successfully!",
                "success"
            )

            print(
                "Redirecting to customer dashboard..."
            )

            return redirect(
                url_for("customer.dashboard")
            )

        print("SIGNUP ERRORS:", errors)

        for e in errors:
            flash(e, "danger")

    return render_template(
        "auth/customer_signup.html"
    )


# ============================================================
# LOGOUT
# ============================================================

@auth_bp.route("/logout")
def logout():

    session.clear()

    flash(
        "Logged out successfully.",
        "info"
    )

    return redirect(
        url_for("auth.login")
    )
