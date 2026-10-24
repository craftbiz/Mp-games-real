import re
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.security import (
    generate_password_hash, check_password_hash
)

import database

auth_bp = Blueprint("auth", __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")

        if not user_id or not database.get_user_by_id(user_id):
            session.clear()
            if request.path.startswith("/api/"):
                return {"error": "Please log in first."}, 401
            return redirect(url_for("auth.login"))

        return view(*args, **kwargs)

    return wrapped


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not 3 <= len(username) <= 24:
            flash("Username must be 3–24 characters.", "error")
        elif not re.fullmatch(r"[A-Za-z0-9_-]+", username):
            flash(
                "Use only letters, numbers, underscores and hyphens.",
                "error"
            )
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
        elif len(password) > 128:
            flash("Password is too long.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            try:
                user = database.create_user(
                    username,
                    generate_password_hash(password)
                )
                session.clear()
                session["user_id"] = user["user_id"]
                session["username"] = user["username"]
                return redirect(url_for("home"))

            except ValueError as exc:
                flash(str(exc), "error")
            except Exception:
                # A duplicate username is the most likely cause.
                flash(
                    "Registration failed. That username may already "
                    "be taken.",
                    "error"
                )

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = database.get_user_by_username(username)

        if user and check_password_hash(
            user["password_hash"], password
        ):
            session.clear()
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            return redirect(url_for("home"))

        flash("Incorrect username or password.", "error")

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("auth.login"))