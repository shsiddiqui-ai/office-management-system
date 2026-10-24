import os
import secrets
import sqlite3

from datetime import timedelta, datetime
from functools import wraps
from contextlib import closing

import click

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    abort
)

from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)


from database.reporting import (
    upgrade_reporting, root_post_id, authority_posts,
    set_post_parent, set_division_authority, current_structure_plan, record_unit_parent
)


app = Flask(
    __name__,
    instance_relative_config=True
)


# =================================================
# SECURE SESSION CONFIGURATION
# =================================================

# Local instance folder GitHub par upload nahi hoga.
os.makedirs(
    app.instance_path,
    exist_ok=True
)

secret_key_file = os.path.join(
    app.instance_path,
    "secret_key"
)

# Production/LAN server par environment variable ko priority milegi.
secret_key = os.environ.get("OMS_SECRET_KEY")

# Environment variable na ho to local secret file use hogi.
if not secret_key:

    if os.path.exists(secret_key_file):

        with open(
            secret_key_file,
            "r",
            encoding="utf-8"
        ) as file:

            secret_key = file.read().strip()

    else:

        secret_key = secrets.token_hex(32)

        with open(
            secret_key_file,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(secret_key)


app.config.update(
    SECRET_KEY=secret_key,

    DATABASE=os.environ.get("OMS_DATABASE", "database/office.db"),

    SESSION_COOKIE_NAME=(
        "oms_demo_session"
        if os.path.basename(os.environ.get("OMS_DATABASE", "database/office.db")).lower() == "office_demo.db"
        else "session"
    ),

    SESSION_COOKIE_HTTPONLY=True,

    SESSION_COOKIE_SECURE=os.environ.get("OMS_COOKIE_SECURE") == "1",

    SESSION_COOKIE_SAMESITE="Lax",

    PERMANENT_SESSION_LIFETIME=timedelta(
        minutes=30
    )
)


def get_db_connection():
    connection = sqlite3.connect(app.config.get("DATABASE", "database/office.db"))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def clean_name(value):
    return " ".join(value.strip().split())

# =================================================
# INITIAL SUPER ADMIN ACCOUNT
# =================================================

@app.cli.command("create-super-admin")
@click.option(
    "--pin",
    prompt="Employee PIN"
)
def create_super_admin(pin):

    pin = pin.strip()

    if not pin or not pin.isdigit():

        raise click.ClickException(
            "Employee PIN must contain digits only."
        )

    connection = get_db_connection()

    employee = connection.execute("""
        SELECT
            id,
            pin,
            name,
            is_active
        FROM employees
        WHERE pin = ?
    """, (pin,)).fetchone()

    if employee is None:

        connection.close()

        raise click.ClickException(
            "No employee exists with this PIN."
        )

    if employee["is_active"] == 0:

        connection.close()

        raise click.ClickException(
            "An inactive employee cannot receive a login account."
        )

    existing_account = connection.execute("""
        SELECT id
        FROM user_accounts
        WHERE employee_id = ?
    """, (employee["id"],)).fetchone()

    if existing_account is not None:

        connection.close()

        raise click.ClickException(
            "This employee already has a user account."
        )

    super_admin_role = connection.execute("""
        SELECT id
        FROM system_roles
        WHERE name = 'Super Admin'
          AND is_active = 1
    """).fetchone()

    if super_admin_role is None:

        connection.close()

        raise click.ClickException(
            "Super Admin role is missing from the database."
        )

    password = click.prompt(
        "Temporary password",
        hide_input=True,
        confirmation_prompt=True
    )

    if len(password) < 12:

        connection.close()

        raise click.ClickException(
            "Password must contain at least 12 characters."
        )

    password_hash = generate_password_hash(
        password
    )

    try:

        cursor = connection.execute("""
            INSERT INTO user_accounts
            (
                employee_id,
                password_hash,
                must_change_password
            )
            VALUES (?, ?, 1)
        """, (
            employee["id"],
            password_hash
        ))

        user_account_id = cursor.lastrowid

        connection.execute("""
            INSERT INTO user_role_assignments
            (
                user_account_id,
                system_role_id,
                assigned_by_user_account_id
            )
            VALUES (?, ?, NULL)
        """, (
            user_account_id,
            super_admin_role["id"]
        ))

        connection.commit()

    except sqlite3.IntegrityError as error:

        connection.rollback()
        connection.close()

        raise click.ClickException(
            f"Super Admin account could not be created: {error}"
        )

    connection.close()

    click.echo(
        "Super Admin account created successfully for "
        f"{employee['name']} (PIN: {employee['pin']})."
    )


    # =================================================
# RESET USER PASSWORD CLI COMMAND
# =================================================

@app.cli.command("reset-user-password")
@click.option(
    "--pin",
    prompt="Employee PIN"
)
def reset_user_password(pin):

    pin = pin.strip()

    if not pin or not pin.isdigit():

        raise click.ClickException(
            "Employee PIN must contain digits only."
        )

    connection = get_db_connection()

    account = connection.execute("""
        SELECT
            user_accounts.id AS user_account_id,
            user_accounts.is_active AS account_is_active,

            employees.pin,
            employees.name AS employee_name,
            employees.is_active AS employee_is_active

        FROM user_accounts

        JOIN employees
            ON user_accounts.employee_id
               = employees.id

        WHERE employees.pin = ?
    """, (pin,)).fetchone()

    if account is None:

        connection.close()

        raise click.ClickException(
            "No user account exists for this employee PIN."
        )

    if (
        account["account_is_active"] == 0
        or account["employee_is_active"] == 0
    ):

        connection.close()

        raise click.ClickException(
            "Password cannot be reset for an inactive account."
        )

    password = click.prompt(
        "New temporary password",
        hide_input=True,
        confirmation_prompt=True
    )

    if len(password) < 12:

        connection.close()

        raise click.ClickException(
            "Password must contain at least 12 characters."
        )

    password_hash = generate_password_hash(
        password
    )

    connection.execute("""
        UPDATE user_accounts

        SET password_hash = ?,
            must_change_password = 1,
            failed_login_attempts = 0,
            locked_until = NULL,
            password_changed_at = NULL,
            updated_at = CURRENT_TIMESTAMP

        WHERE id = ?
    """, (
        password_hash,
        account["user_account_id"]
    ))

    connection.commit()
    connection.close()

    click.echo(
        "Password reset successfully for "
        f"{account['employee_name']} "
        f"(PIN: {account['pin']})."
    )

# =================================================
# LOGIN / LOGOUT
# =================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    # Logged-in user ko login form dobara na dikhayein.
    if session.get("user_account_id") is not None:
        return redirect("/admin")

    error = None

    if request.method == "POST":

        pin = request.form.get(
            "pin",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if not pin or not password:

            error = "PIN and password are required."

        elif not pin.isdigit():

            error = "Invalid PIN or password."

        else:

            connection = get_db_connection()

            account = connection.execute("""
                SELECT
                    user_accounts.id AS user_account_id,
                    user_accounts.employee_id,
                    user_accounts.password_hash,
                    user_accounts.is_active
                        AS account_is_active,
                    user_accounts.must_change_password,
                    user_accounts.failed_login_attempts,
                    user_accounts.locked_until,

                    employees.pin,
                    employees.name AS employee_name,
                    employees.is_active
                        AS employee_is_active,

                    CASE
                        WHEN user_accounts.locked_until IS NOT NULL
                         AND datetime(user_accounts.locked_until)
                             > datetime('now')
                        THEN 1
                        ELSE 0
                    END AS is_locked

                FROM user_accounts

                JOIN employees
                    ON user_accounts.employee_id
                       = employees.id

                WHERE employees.pin = ?
            """, (pin,)).fetchone()

            if (
                account is None
                or account["account_is_active"] == 0
                or account["employee_is_active"] == 0
            ):

                error = "Invalid PIN or password."

            elif account["is_locked"] == 1:

                error = (
                    "This account is temporarily locked. "
                    "Please try again after 15 minutes."
                )

            elif not check_password_hash(
                account["password_hash"],
                password
            ):

                failed_attempts = (
                    account["failed_login_attempts"] + 1
                )

                if failed_attempts >= 5:

                    connection.execute("""
                        UPDATE user_accounts
                        SET failed_login_attempts = 0,
                            locked_until = datetime(
                                'now',
                                '+15 minutes'
                            ),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (
                        account["user_account_id"],
                    ))

                    error = (
                        "Too many failed attempts. "
                        "This account is locked for 15 minutes."
                    )

                else:

                    connection.execute("""
                        UPDATE user_accounts
                        SET failed_login_attempts = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (
                        failed_attempts,
                        account["user_account_id"]
                    ))

                    error = "Invalid PIN or password."

                connection.commit()

            else:

                # Successful login par failed-attempt state reset hogi.
                connection.execute("""
                    UPDATE user_accounts
                    SET failed_login_attempts = 0,
                        locked_until = NULL,
                        last_login_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    account["user_account_id"],
                ))

                connection.commit()

                session.clear()
                session.permanent = True

                session["user_account_id"] = (
                    account["user_account_id"]
                )

                session["employee_id"] = (
                    account["employee_id"]
                )

                connection.close()

                # Temporary password ko first login par change karna hoga.
                if account["must_change_password"] == 1:
                    return redirect("/change-password")

                return redirect("/admin")

            connection.close()

    return render_template(
        "login.html",
        error=error
    )


@app.route("/logout", methods=["POST"])
def logout():

    session.clear()

    return redirect("/login")


# =================================================
# CHANGE PASSWORD
# =================================================

@app.route(
    "/change-password",
    methods=["GET", "POST"]
)
def change_password():

    user_account_id = session.get(
        "user_account_id"
    )

    if user_account_id is None:
        return redirect("/login")

    connection = get_db_connection()

    account = connection.execute("""
        SELECT
            user_accounts.id,
            user_accounts.password_hash,
            user_accounts.is_active
                AS account_is_active,

            employees.pin,
            employees.name AS employee_name,
            employees.is_active
                AS employee_is_active

        FROM user_accounts

        JOIN employees
            ON user_accounts.employee_id
               = employees.id

        WHERE user_accounts.id = ?
    """, (user_account_id,)).fetchone()

    if (
        account is None
        or account["account_is_active"] == 0
        or account["employee_is_active"] == 0
    ):

        connection.close()
        session.clear()

        return redirect("/login")

    error = None

    if request.method == "POST":

        current_password = request.form.get(
            "current_password",
            ""
        )

        new_password = request.form.get(
            "new_password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if (
            not current_password
            or not new_password
            or not confirm_password
        ):

            error = "All password fields are required."

        elif not check_password_hash(
            account["password_hash"],
            current_password
        ):

            error = "Current password is incorrect."

        elif len(new_password) < 12:

            error = (
                "New password must contain at least "
                "12 characters."
            )

        elif new_password != confirm_password:

            error = (
                "New password and confirmation do not match."
            )

        elif check_password_hash(
            account["password_hash"],
            new_password
        ):

            error = (
                "New password must be different from "
                "the current password."
            )

        else:

            new_password_hash = generate_password_hash(
                new_password
            )

            connection.execute("""
                UPDATE user_accounts
                SET password_hash = ?,
                    must_change_password = 0,
                    failed_login_attempts = 0,
                    locked_until = NULL,
                    password_changed_at =
                        CURRENT_TIMESTAMP,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                new_password_hash,
                user_account_id
            ))

            connection.commit()
            connection.close()

            return redirect("/admin")

    connection.close()

    return render_template(
        "change_password.html",
        account=account,
        error=error
    )
# =================================================
# GLOBAL AUTHENTICATION PROTECTION
# =================================================

ADMIN_ENDPOINT_PERMISSIONS = {
    "admin_dashboard": "dashboard.view",
    "manage_user_accounts": "accounts.manage",
    "set_login_account_status": "accounts.manage",
    "organization_hierarchy": "organization.view",
    "manage_units": "organization.view",
    "manage_designations": "organization.view",
    "manage_employees": "employees.view",
    "manage_posts": "organization.view",
    "add_employee": "employees.manage",
    "edit_employee": "employees.manage",
    "add_unit": "organization.manage",
    "edit_unit": "organization.manage",
    "deactivate_unit": "organization.manage",
    "reactivate_unit": "organization.manage",
    "add_designation": "organization.manage",
    "delete_designation": "organization.manage",
    "assign_post": "organization.manage",
    "end_post_assignment": "organization.manage",
    "manage_division_management": "organization.manage",
    "manage_section_head": "organization.manage",
    "manage_division_reporting_authority": "organization.manage",
    "manage_reporting_posts": "organization.manage",
    "change_reporting_post": "organization.manage",
}


def account_has_permission(code):
    with closing(get_db_connection()) as connection:
        return connection.execute("""
            SELECT 1 FROM user_role_assignments a
            JOIN system_roles r ON r.id=a.system_role_id AND r.is_active=1
            JOIN system_role_permissions rp ON rp.system_role_id=r.id
            JOIN permissions p ON p.id=rp.permission_id AND p.is_active=1
            WHERE a.user_account_id=? AND a.is_active=1 AND p.code=?
        """, (session.get("user_account_id"),code)).fetchone() is not None


@app.before_request
def enforce_authentication():

    # Flask ko matching route na mile to normal 404 process hone dein.
    if request.endpoint is None:
        return None

    # Login page aur static files login ke baghair available rahenge.
    public_endpoints = {
        "login",
        "static"
    }

    if request.endpoint in public_endpoints:
        return None

    user_account_id = session.get(
        "user_account_id"
    )

    # Session mein login account na ho to login page par bhejein.
    if user_account_id is None:
        return redirect("/login")

    connection = get_db_connection()

    account = connection.execute("""
        SELECT
            user_accounts.id,
            user_accounts.is_active
                AS account_is_active,
            user_accounts.must_change_password,

            employees.is_active
                AS employee_is_active

        FROM user_accounts

        JOIN employees
            ON user_accounts.employee_id
               = employees.id

        WHERE user_accounts.id = ?
    """, (user_account_id,)).fetchone()

    connection.close()

    # Deleted, inactive ya invalid account ki session remove karein.
    if (
        account is None
        or account["account_is_active"] == 0
        or account["employee_is_active"] == 0
    ):

        session.clear()
        return redirect("/login")

    # Temporary password change kiye baghair
    # kisi aur page par jane ki permission nahi hogi.
    password_change_endpoints = {
        "change_password",
        "logout"
    }

    if (
        account["must_change_password"] == 1
        and request.endpoint
            not in password_change_endpoints
    ):
        return redirect("/change-password")

    if request.path.startswith("/admin"):
        permission = ADMIN_ENDPOINT_PERMISSIONS.get(request.endpoint, "organization.manage")
        if not account_has_permission(permission):
            abort(403)
    elif request.endpoint in ("cd_dvd", "new_dvd_request"):
        if not account_has_permission("dvd.request.create"):
            abort(403)

    return None

# =================================================
# CD/DVD - APPROVAL ACCESS PERMISSION HELPER
# =================================================

def dvd_approval_access_required(view):
    @wraps(view)
    def protected(*args, **kwargs):

        allowed_permissions = (
            "dvd.request.manager_approve",
            "dvd.request.cyber_review",
            "dvd.request.technical_process"
        )

        if not any(
            account_has_permission(permission)
            for permission in allowed_permissions
        ):
            abort(403)

        return view(*args, **kwargs)

    return protected

def organization_manager_required(view):
    @wraps(view)
    def protected(*args, **kwargs):
        connection = get_db_connection()
        allowed = connection.execute("""
            SELECT 1 FROM user_role_assignments AS assignment
            JOIN system_roles AS role ON role.id=assignment.system_role_id AND role.is_active=1
            JOIN system_role_permissions AS grant_rule ON grant_rule.system_role_id=role.id
            JOIN permissions AS permission ON permission.id=grant_rule.permission_id AND permission.is_active=1
            WHERE assignment.user_account_id=? AND assignment.is_active=1
              AND permission.code='organization.manage'
        """, (session.get("user_account_id"),)).fetchone()
        connection.close()
        if not allowed:
            abort(403)
        return view(*args, **kwargs)
    return protected


def backup_database(connection):
    path = app.config.get("DATABASE", "database/office.db")
    backup_path = os.path.splitext(path)[0] + "_before_reporting_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".db"
    with closing(sqlite3.connect(backup_path)) as backup:
        connection.backup(backup)
    return backup_path


@app.cli.command("upgrade-reporting")
def upgrade_reporting_command():
    """Back up the local database and enable editable authority reporting."""
    connection = get_db_connection()
    try:
        click.echo("Backup: " + backup_database(connection))
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            upgrade_reporting(connection)
    finally:
        connection.close()
    click.echo("Reporting schema upgraded. Existing Division assignments were preserved.")


@app.cli.command("apply-current-hierarchy")
@click.option("--apply", is_flag=True, help="Apply the previewed structure to the local database.")
@click.option("--create-missing", is_flag=True, help="Create confirmed Divisions that do not yet exist.")
def apply_current_hierarchy_command(apply, create_missing):
    """Preview/apply the confirmed 05 October 2026 reporting structure."""
    connection = get_db_connection()
    try:
        if apply:
            click.echo("Backup: " + backup_database(connection))
            connection.execute("BEGIN IMMEDIATE")
        plan = current_structure_plan(connection)
        for name, authority, unit_id in plan:
            click.echo(f"{name} -> {authority}" + (" [missing]" if unit_id is None else ""))
        if not apply:
            click.echo("Preview only. No database changes made.")
            return
        if any(unit_id is None for _, _, unit_id in plan) and not create_missing:
            raise ValueError("Some Divisions are missing. Add them first or use --create-missing after reviewing the preview.")
        ids = {row["name"]: row["id"] for row in authority_posts(connection)}
        # The command sets today's confirmed PM/DPM relationship; future edits use the admin screen.
        for child, parent in (("Plant Manager", "Senior Director"), ("Deputy Plant Manager", "Plant Manager")):
            if child not in ids or parent not in ids:
                raise ValueError("Default authority names changed. Apply reporting through the admin screens instead.")
            set_post_parent(connection, ids[child], ids[parent])
        for name, authority, unit_id in plan:
            if unit_id is None:
                cursor = connection.execute("INSERT INTO organizational_units(name,unit_type) VALUES (?,'Division')", (name,))
                unit_id = cursor.lastrowid
                record_unit_parent(connection, unit_id, None)
                connection.execute("INSERT INTO organizational_unit_name_history(organizational_unit_id,name,normalized_name,is_current) VALUES (?,?,?,1)", (unit_id,name,name.lower()))
            set_division_authority(connection, unit_id, ids[authority])
        connection.commit()
        click.echo("Current hierarchy applied. Prior reporting history preserved.")
    except (ValueError, sqlite3.IntegrityError) as error:
        connection.rollback()
        raise click.ClickException(str(error))
    finally:
        connection.close()


@app.route("/admin/reporting-posts", methods=["GET", "POST"])
@organization_manager_required
def manage_reporting_posts():
    connection = get_db_connection()
    error = None
    try:
        if request.method == "POST":
            if request.form.get("csrf_token") != session.get("reporting_csrf_token") or not session.get("reporting_csrf_token"):
                abort(400)
            name = clean_name(request.form.get("name", ""))
            parent_value = request.form.get("parent_post_id", "")
            if not name or not parent_value.isdigit():
                raise ValueError("Enter a post name and select its reporting authority.")
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute("INSERT INTO posts(name,max_active_holders,is_reporting_authority) VALUES (?,1,1)", (name,))
            set_post_parent(connection, cursor.lastrowid, int(parent_value))
            connection.commit()
            return redirect("/admin/reporting-posts")
    except (ValueError, sqlite3.IntegrityError) as exc:
        connection.rollback()
        error = str(exc) if isinstance(exc, ValueError) else "A post with this name already exists."
    finally:
        if request.method == "POST" and error is None:
            connection.close()
    root = root_post_id(connection)
    posts = connection.execute("""SELECT p.id,p.name,r.parent_post_id,parent.name AS parent_name
        FROM posts p LEFT JOIN post_reporting_assignments r ON r.post_id=p.id AND r.is_active=1
        LEFT JOIN posts parent ON parent.id=r.parent_post_id
        WHERE p.is_active=1 AND p.is_reporting_authority=1 ORDER BY p.name""").fetchall()
    history = connection.execute("""SELECT p.name,parent.name AS parent_name,r.start_date,r.end_date,r.is_active
        FROM post_reporting_assignments r JOIN posts p ON p.id=r.post_id
        JOIN posts parent ON parent.id=r.parent_post_id ORDER BY r.id DESC""").fetchall()
    connection.close()
    session.setdefault("reporting_csrf_token", secrets.token_hex(32))
    return render_template("reporting_posts.html", posts=posts, history=history, root_id=root, error=error), (400 if error else 200)


@app.route("/admin/reporting-posts/<int:post_id>", methods=["POST"])
@organization_manager_required
def change_reporting_post(post_id):
    if not session.get("reporting_csrf_token") or request.form.get("csrf_token") != session["reporting_csrf_token"]:
        abort(400)
    connection = get_db_connection()
    try:
        parent_value = request.form.get("parent_post_id", "")
        if not parent_value.isdigit():
            raise ValueError("Select a reporting authority.")
        connection.execute("BEGIN IMMEDIATE")
        set_post_parent(connection, post_id, int(parent_value))
        connection.commit()
    except (ValueError, sqlite3.IntegrityError) as error:
        connection.rollback()
        return str(error), 400
    finally:
        connection.close()
    return redirect("/admin/reporting-posts")


@app.after_request
def mark_demo_database(response):
    # A clear marker helps users distinguish sandbox data from their own database.
    if response.mimetype != "text/html" or response.direct_passthrough:
        return response
    connection = None
    try:
        connection = get_db_connection()
        has_marker = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_metadata'"
        ).fetchone()
        is_demo = has_marker and connection.execute(
            "SELECT 1 FROM demo_metadata WHERE marker='OMS_DEMO_V1'"
        ).fetchone()
    except sqlite3.Error:
        is_demo = False
    finally:
        if connection is not None:
            connection.close()
    if is_demo:
        import re
        banner = ('<div style="background:#fff1cc;color:#613900;padding:12px;'
                  'text-align:center;font:700 15px Arial;border-bottom:2px solid #d89500">'
                  'DEMO DATABASE — fictional staff for testing</div>')
        response.set_data(re.sub(r'(<body\b[^>]*>)', lambda match: match.group(1) + banner,
                                 response.get_data(as_text=True), count=1, flags=re.IGNORECASE))
    return response


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/cd-dvd")
def cd_dvd():
    return render_template("cd_dvd.html")


# =================================================
# ISSUED DVD REGISTER — DEMO, READ ONLY
# =================================================
@app.route("/dvd-discs/issued")
def issued_dvd_register():
    if not account_has_permission("dvd.request.technical_process"):
        abort(403)
    if not session.get("dvd_approval_csrf_token"):
        session["dvd_approval_csrf_token"] = secrets.token_urlsafe(32)
    connection = get_db_connection()
    try:
        demo_table = connection.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='demo_metadata'
        """).fetchone()
        marker = (connection.execute(
            "SELECT 1 FROM demo_metadata WHERE marker='OMS_DEMO_V1'"
        ).fetchone() if demo_table else None)
        if not marker:
            abort(403)
        discs = connection.execute("""
            SELECT d.id, d.number, d.state, d.allocated_at, d.handed_at,
                   d.request_id, d.generation, d.replacement_pending,
                   r.dvd_category, e.name AS requester_name, e.pin AS requester_pin
            FROM dvd_discs AS d
            JOIN dvd_requests AS r ON r.id=d.request_id
            JOIN employees AS e ON e.id=r.requester_employee_id
            WHERE d.handed_at IS NOT NULL
            ORDER BY d.handed_at DESC, d.id DESC
            LIMIT 500
        """).fetchall()
    finally:
        connection.close()
    return render_template("issued_dvds.html", discs=discs)

# DEMO ONLY: faulty -> shredded -> replacement, with atomic audit
@app.route("/dvd-disc/<int:disc_id>/<operation>", methods=["POST"])
def demo_dvd_lifecycle(disc_id, operation):
    import json
    from datetime import datetime as _datetime
    if operation not in ("faulty", "shred", "replace"):
        abort(404)
    if os.path.basename(app.config["DATABASE"]).lower() != "office_demo.db":
        abort(403)
    if not account_has_permission("dvd.request.technical_process"):
        abort(403)
    if not request.form.get("csrf_token") or not secrets.compare_digest(
        request.form["csrf_token"], session.get("dvd_approval_csrf_token", "")
    ):
        abort(400)
    if request.form.get("confirm") != "yes":
        abort(400)
    note = request.form.get("reason", "").strip()
    if len(note) > 300 or (operation == "faulty" and not note):
        abort(400)
    connection = get_db_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        exists = connection.execute("""SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='demo_metadata'""").fetchone()
        if not exists or not connection.execute("""SELECT 1 FROM demo_metadata
            WHERE marker='OMS_DEMO_V1'""").fetchone():
            abort(403)
        actor = connection.execute("""SELECT a.id, e.id employee_id, e.name, e.pin
            FROM user_accounts a JOIN employees e ON a.employee_id=e.id
            WHERE a.id=? AND a.is_active=1 AND e.is_active=1""",
            (session["user_account_id"],)).fetchone()
        if not actor:
            abort(403)
        disc = connection.execute("""SELECT d.*, r.dvd_category,
            r.status AS request_status, r.requester_employee_id
            FROM dvd_discs d JOIN dvd_requests r ON r.id=d.request_id
            WHERE d.id=?""", (disc_id,)).fetchone()
        if not disc:
            abort(404)
        if disc["dvd_category"] not in ("Internal", "Internet") or disc["request_status"] != "Issued":
            abort(409)
        if disc["requester_employee_id"] == actor["employee_id"]:
            abort(403)
        now = _datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_number = None
        if operation == "faulty":
            if disc["state"] != "Issued" or disc["replacement_pending"]:
                abort(409)
            changed = connection.execute("""UPDATE dvd_discs
                SET state='Faulty', replacement_pending=1, notes=?
                WHERE id=? AND state='Issued' AND replacement_pending=0""",
                (note, disc_id)).rowcount
            action = "dvd_marked_faulty"
        elif operation == "shred":
            if disc["state"] != "Faulty" or disc["replacement_pending"] != 1:
                abort(409)
            changed = connection.execute("""UPDATE dvd_discs
                SET state='Shredded', shredded_at=?
                WHERE id=? AND state='Faulty' AND replacement_pending=1""",
                (now, disc_id)).rowcount
            action = "dvd_faulty_shredded"
        else:
            if disc["state"] != "Shredded" or disc["replacement_pending"] != 1:
                abort(409)
            if connection.execute("SELECT 1 FROM dvd_discs WHERE replaces_id=?", (disc_id,)).fetchone():
                abort(409)
            category=disc["dvd_category"]; year=_datetime.now().year
            prefix={"Internal":"INT","Internet":"NET"}[category]
            counter=connection.execute("""SELECT next_serial FROM dvd_counters
                WHERE category=? AND year=?""",(category,year)).fetchone()
            serial=counter["next_serial"] if counter else 1
            if serial < 1:
                abort(409)
            new_number=f"{prefix}-{year}-{serial:06d}"
            connection.execute("""INSERT INTO dvd_discs
                (request_id,number,base_number,generation,replaces_id,state,allocated_at,handed_at,notes)
                VALUES (?,?,?,?,?,'Issued',?,?,?)""",
                (disc["request_id"],new_number,disc["base_number"],disc["generation"]+1,
                 disc_id,now,now,"Replacement of "+disc["number"]))
            if counter:
                connection.execute("""UPDATE dvd_counters SET next_serial=?
                    WHERE category=? AND year=?""",(serial+1,category,year))
            else:
                connection.execute("""INSERT INTO dvd_counters (category,year,next_serial)
                    VALUES (?,?,?)""",(category,year,serial+1))
            changed=connection.execute("""UPDATE dvd_discs
                SET replacement_pending=0 WHERE id=? AND state='Shredded'
                AND replacement_pending=1""",(disc_id,)).rowcount
            action="dvd_replacement_issued"
        if changed != 1:
            abort(409)
        connection.execute("""INSERT INTO dvd_events
            (request_id,disc_id,actor_account_id,actor_snapshot,action,details)
            VALUES (?,?,?,?,?,?)""",
            (disc["request_id"],disc_id,actor["id"],
             json.dumps({"pin":actor["pin"],"name":actor["name"]}),action,
             json.dumps({"old_number":disc["number"],"new_number":new_number,"reason":note})))
        connection.commit()
    finally:
        connection.close()
    return redirect("/dvd-discs/issued")


# Demo-only ordinary return and shredding of Internal/Internet DVDs.
@app.route('/dvd-discs/normal-closure', methods=['GET'])
def demo_normal_closure_page():
    if os.path.basename(app.config['DATABASE']).lower() != 'office_demo.db':
        abort(403)
    if not account_has_permission('dvd.request.technical_process'):
        abort(403)
    import secrets as _secrets
    if not session.get('dvd_normal_closure_token'):
        session['dvd_normal_closure_token'] = _secrets.token_urlsafe(32)
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_metadata'").fetchone():
            abort(403)
        if not conn.execute("SELECT 1 FROM demo_metadata WHERE marker='OMS_DEMO_V1'").fetchone():
            abort(403)
        discs = conn.execute("""
            SELECT d.id, d.request_id, d.number, d.state, d.replacement_pending,
                   d.returned_at, d.shredded_at, d.generation,
                   r.dvd_category, r.status AS request_status,
                   e.name AS requester_name, e.pin AS requester_pin
            FROM dvd_discs d
            JOIN dvd_requests r ON r.id=d.request_id
            JOIN employees e ON e.id=r.requester_employee_id
            WHERE r.dvd_category IN ('Internal','Internet')
              AND d.state IN ('Issued','Returned','Shredded')
            ORDER BY d.id DESC LIMIT 500
        """).fetchall()
    finally:
        conn.close()
    return render_template('dvd_normal_closure.html', discs=discs,
                           csrf_token=session['dvd_normal_closure_token'])


@app.route('/dvd-discs/<int:disc_id>/normal-closure/<operation>', methods=['POST'])
def demo_normal_closure_action(disc_id, operation):
    import json as _json
    import secrets as _secrets
    if operation not in ('return', 'shred'):
        abort(404)
    if os.path.basename(app.config['DATABASE']).lower() != 'office_demo.db':
        abort(403)
    if not account_has_permission('dvd.request.technical_process'):
        abort(403)
    submitted = request.form.get('csrf_token', '')
    stored = session.get('dvd_normal_closure_token', '')
    if not submitted or not stored or not _secrets.compare_digest(submitted, stored):
        abort(400)
    if request.form.get('confirmed') != 'yes':
        abort(400)
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_metadata'").fetchone() or not conn.execute("SELECT 1 FROM demo_metadata WHERE marker='OMS_DEMO_V1'").fetchone():
            abort(403)
        actor = conn.execute("""
            SELECT a.id AS account_id, e.id AS employee_id, e.name, e.pin
            FROM user_accounts a JOIN employees e ON e.id=a.employee_id
            WHERE a.id=? AND a.is_active=1 AND e.is_active=1
        """, (session['user_account_id'],)).fetchone()
        if not actor:
            abort(403)
        disc = conn.execute("""
            SELECT d.id,d.number,d.request_id,d.state,d.replacement_pending,
                   r.dvd_category,r.status,r.requester_employee_id
            FROM dvd_discs d JOIN dvd_requests r ON r.id=d.request_id
            WHERE d.id=?
        """, (disc_id,)).fetchone()
        if not disc:
            abort(404)
        if actor['employee_id'] == disc['requester_employee_id']:
            abort(403)
        if disc['dvd_category'] not in ('Internal','Internet') or disc['status'] != 'Issued':
            abort(409)
        if disc['replacement_pending']:
            abort(409)
        if operation == 'return':
            if disc['state'] != 'Issued':
                abort(409)
            change = conn.execute("""
                UPDATE dvd_discs SET state='Returned',returned_at=CURRENT_TIMESTAMP
                WHERE id=? AND state='Issued' AND replacement_pending=0
            """, (disc_id,))
            action = 'dvd_normal_returned'
        else:
            if disc['state'] != 'Returned':
                abort(409)
            change = conn.execute("""
                UPDATE dvd_discs SET state='Shredded',shredded_at=CURRENT_TIMESTAMP
                WHERE id=? AND state='Returned' AND replacement_pending=0
            """, (disc_id,))
            action = 'dvd_normal_shredded'
        if change.rowcount != 1:
            abort(409)
        conn.execute("""
            INSERT INTO dvd_events(request_id,disc_id,actor_account_id,actor_snapshot,action,details)
            VALUES (?,?,?,?,?,?)
        """, (disc['request_id'],disc_id,actor['account_id'],
              _json.dumps({'name':actor['name'],'pin':actor['pin']}),action,
              _json.dumps({'number':disc['number'],'demo':True})))
        if operation == 'shred':
            remaining = conn.execute("""
                SELECT COUNT(*) FROM dvd_discs
                WHERE request_id=? AND (state!='Shredded' OR replacement_pending!=0)
            """, (disc['request_id'],)).fetchone()[0]
            if remaining == 0:
                changed = conn.execute("""
                    UPDATE dvd_requests SET status='Closed'
                    WHERE id=? AND status='Issued'
                """, (disc['request_id'],))
                if changed.rowcount == 1:
                    conn.execute("""
                        INSERT INTO dvd_events(request_id,actor_account_id,actor_snapshot,action,details)
                        VALUES (?,?,?,?,?)
                    """, (disc['request_id'],actor['account_id'],
                          _json.dumps({'name':actor['name'],'pin':actor['pin']}),
                          'dvd_request_closed',_json.dumps({'demo':True,'reason':'all_discs_shredded'})))
        conn.commit()
    finally:
        conn.close()
    return redirect('/dvd-discs/normal-closure')

@app.route("/admin")
def admin_dashboard():
    return render_template("admin.html")

# =================================================
# ORGANIZATION HIERARCHY
# =================================================

@app.route("/admin/organization-hierarchy")
def organization_hierarchy():

    connection = get_db_connection()

    top_authorities = connection.execute("""
        SELECT posts.id, posts.name AS post_name,
               employees.pin, employees.name AS employee_name,
               reporting.parent_post_id, parent.name AS parent_name
        FROM posts
        LEFT JOIN employee_post_assignments AS holder
          ON holder.post_id=posts.id AND holder.is_active=1
        LEFT JOIN employees ON holder.employee_id=employees.id AND employees.is_active=1
        LEFT JOIN post_reporting_assignments AS reporting
          ON reporting.post_id=posts.id AND reporting.is_active=1
        LEFT JOIN posts AS parent ON parent.id=reporting.parent_post_id
        WHERE posts.is_active=1 AND posts.is_reporting_authority=1
        ORDER BY posts.name COLLATE NOCASE
    """).fetchall()

    # Har active Division ki reporting authority aur current management.
    divisions = connection.execute("""
        SELECT
            division.id,
            division.name,

            authority_post.name AS authority_post_name,
            reporting.authority_post_id,

            management.responsibility_type,
            manager.pin AS manager_pin,
            manager.name AS manager_name

        FROM organizational_units AS division

        LEFT JOIN division_reporting_assignments AS reporting
            ON reporting.division_id = division.id
           AND reporting.is_active = 1

        LEFT JOIN posts AS authority_post
            ON reporting.authority_post_id = authority_post.id

        LEFT JOIN division_management_assignments AS management
            ON management.division_id = division.id
           AND management.is_active = 1

        LEFT JOIN employees AS manager
            ON management.employee_id = manager.id

        WHERE division.unit_type = 'Division'
          AND division.is_active = 1

        ORDER BY
            CASE authority_post.name
                WHEN 'Senior Director' THEN 1
                WHEN 'Plant Manager' THEN 2
                WHEN 'Deputy Plant Manager' THEN 3
                ELSE 4
            END,
            division.name
    """).fetchall()

    # Har active Section aur uska current Head.
    sections = connection.execute("""
        SELECT
            section.id,
            section.name,
            section.parent_id AS division_id,
            division.name AS division_name,

            head_employee.pin AS head_pin,
            head_employee.name AS head_name

        FROM organizational_units AS section

        JOIN organizational_units AS division
            ON section.parent_id = division.id
           AND division.unit_type = 'Division'
           AND division.is_active = 1

        LEFT JOIN section_head_assignments AS head_assignment
            ON head_assignment.section_id = section.id
           AND head_assignment.is_active = 1

        LEFT JOIN employees AS head_employee
            ON head_assignment.employee_id = head_employee.id

        WHERE section.unit_type = 'Section'
          AND section.is_active = 1

        ORDER BY
            division.name,
            section.name
    """).fetchall()

    # Active Offices aur unke parent units.
    offices = connection.execute("""
        SELECT
            office.id,
            office.name,
            office.parent_id,
            parent.name AS parent_name,
            parent.unit_type AS parent_type

        FROM organizational_units AS office

        LEFT JOIN organizational_units AS parent
            ON office.parent_id = parent.id

        WHERE office.unit_type = 'Office'
          AND office.is_active = 1

        ORDER BY office.name
    """).fetchall()

    hierarchy_root_id = root_post_id(connection)
    # Unused authority seats stay in admin management, without appearing on forms.
    visible_ids = {hierarchy_root_id}
    visible_ids.update(row["authority_post_id"] for row in divisions if row["authority_post_id"])
    visible_ids.update(row["id"] for row in top_authorities if row["employee_name"])
    parents = {row["id"]: row["parent_post_id"] for row in top_authorities}
    for post_id in list(visible_ids):
        seen = set()
        while post_id in parents and parents[post_id] and post_id not in seen:
            seen.add(post_id)
            post_id = parents[post_id]
            visible_ids.add(post_id)
    top_authorities = [row for row in top_authorities if row["id"] in visible_ids]
    connection.close()

    return render_template(
        "organization_hierarchy.html",
        top_authorities=top_authorities,
        divisions=divisions,
        sections=sections,
        offices=offices,
        root_id=hierarchy_root_id
    )


@app.route("/admin/units")
def manage_units():

    connection = get_db_connection()

    units = connection.execute("""
        SELECT
            unit.id,
            unit.name,
            unit.unit_type,
            unit.parent_id,
            unit.is_active,

            parent.name AS parent_name,

            authority_post.name AS reporting_authority,

            manager_employee.name AS manager_name,

            division_manager.responsibility_type
                AS manager_responsibility,

            head_employee.name AS head_name,

            CASE

                WHEN unit.unit_type = 'Section' THEN (

                    SELECT COUNT(*)
                    FROM employee_location_assignments
                    WHERE section_id = unit.id
                      AND is_active = 1
                )

                ELSE (

                    SELECT COUNT(*)
                    FROM employee_location_assignments
                    WHERE organizational_unit_id = unit.id
                      AND is_active = 1
                )

            END AS employee_count,

            CASE

                WHEN unit.unit_type = 'Division' THEN (

                    SELECT COUNT(*)
                    FROM organizational_units AS child_section
                    WHERE child_section.parent_id = unit.id
                      AND child_section.unit_type = 'Section'
                      AND child_section.is_active = 1
                )

                ELSE 0

            END AS active_section_count

        FROM organizational_units AS unit

        LEFT JOIN organizational_units AS parent
            ON unit.parent_id = parent.id

        LEFT JOIN division_reporting_assignments
            AS division_reporting

            ON division_reporting.division_id = unit.id
           AND division_reporting.is_active = 1

        LEFT JOIN posts AS authority_post
            ON division_reporting.authority_post_id
               = authority_post.id

        LEFT JOIN division_management_assignments
            AS division_manager

            ON division_manager.division_id = unit.id
           AND division_manager.is_active = 1

        LEFT JOIN employees AS manager_employee
            ON division_manager.employee_id
               = manager_employee.id

        LEFT JOIN section_head_assignments
            AS section_head

            ON section_head.section_id = unit.id
           AND section_head.is_active = 1

        LEFT JOIN employees AS head_employee
            ON section_head.employee_id
               = head_employee.id

        ORDER BY

            unit.is_active DESC,

            CASE unit.unit_type
                WHEN 'Division' THEN 1
                WHEN 'Office' THEN 2
                WHEN 'Section' THEN 3
                ELSE 4
            END,

            unit.name
    """).fetchall()

    connection.close()

    return render_template(
        "units.html",
        units=units
    )
@app.route("/admin/units/add", methods=["GET", "POST"])
def add_unit():

    connection = get_db_connection()

    if request.method == "POST":

        name = clean_name(request.form.get("name", ""))
        unit_type = request.form.get("unit_type", "").strip()
        parent_id_value = request.form.get("parent_id", "").strip()

        # Empty ya sirf spaces wala name allow nahi hoga.
        if not name:
            connection.close()
            return "Unit name is required.", 400

        # New structure mein sirf ye three unit types create honge.
        allowed_unit_types = (
            "Division",
            "Office",
            "Section"
        )

        if unit_type not in allowed_unit_types:
            connection.close()
            return "Invalid organizational unit type.", 400

        parent_id = None

        # Section ke liye parent Division lazmi hai.
        if unit_type == "Section":

            if not parent_id_value.isdigit():
                connection.close()
                return "A Section must belong to an active Division.", 400

            parent_id = int(parent_id_value)

            parent_division = connection.execute("""
                SELECT id
                FROM organizational_units
                WHERE id = ?
                  AND unit_type = 'Division'
                  AND is_active = 1
            """, (parent_id,)).fetchone()

            if parent_division is None:
                connection.close()
                return "The selected parent must be an active Division.", 400

        # Division aur Office kisi unit ke child nahi honge.
        else:
            parent_id = None

        # Duplicate checking ke liye relevant existing units load karein.
        if unit_type == "Section":

            existing_units = connection.execute("""
                SELECT id, name, is_active
                FROM organizational_units
                WHERE unit_type = 'Section'
                  AND parent_id = ?
            """, (parent_id,)).fetchall()

        else:

            existing_units = connection.execute("""
                SELECT id, name, is_active
                FROM organizational_units
                WHERE unit_type = ?
            """, (unit_type,)).fetchall()

        normalized_new_name = name.casefold()

        duplicate_unit = None

        for existing_unit in existing_units:

            existing_name = clean_name(
                existing_unit["name"]
            ).casefold()

            if existing_name == normalized_new_name:
                duplicate_unit = existing_unit
                break

        if duplicate_unit:

            connection.close()

            if duplicate_unit["is_active"] == 1:
                return (
                    f"{unit_type} '{name}' already exists.",
                    400
                )

            return (
                f"{unit_type} '{name}' already exists but is inactive. "
                "Reactivate the existing unit instead of creating a duplicate.",
                400
            )

        # New Division, Office ya Section create karein.
        cursor = connection.execute("""
            INSERT INTO organizational_units
            (
                name,
                unit_type,
                parent_id
            )
            VALUES (?, ?, ?)
        """, (
            name,
            unit_type,
            parent_id
        ))

        new_unit_id = cursor.lastrowid
        record_unit_parent(connection, new_unit_id, parent_id)

        # Initial unit name ko history mein bhi save karein.
        connection.execute("""
            INSERT INTO organizational_unit_name_history
            (
                organizational_unit_id,
                name,
                normalized_name,
                start_date,
                is_current
            )
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)
        """, (
            new_unit_id,
            name,
            normalized_new_name
        ))

        connection.commit()
        connection.close()

        return redirect("/admin/units")

    # Section parent dropdown mein sirf active Divisions dikhengi.
    parent_units = connection.execute("""
        SELECT id, name
        FROM organizational_units
        WHERE unit_type = 'Division'
          AND is_active = 1
        ORDER BY name
    """).fetchall()

    connection.close()

    return render_template(
        "add_unit.html",
        parent_units=parent_units
    )

@app.route("/admin/units/edit/<int:unit_id>", methods=["GET", "POST"])
def edit_unit(unit_id):

    connection = get_db_connection()

    unit = connection.execute("""
        SELECT
            id,
            name,
            unit_type,
            parent_id,
            is_active
        FROM organizational_units
        WHERE id = ?
    """, (unit_id,)).fetchone()

    if unit is None:
        connection.close()
        return "Organizational unit not found.", 404

    if request.method == "POST":

        name = clean_name(request.form.get("name", ""))
        parent_id_value = request.form.get(
            "parent_id",
            ""
        ).strip()

        if not name:
            connection.close()
            return "Unit name is required.", 400

        unit_type = unit["unit_type"]
        old_parent_id = unit["parent_id"]
        new_parent_id = old_parent_id

        # Section ka parent hamesha active Division hoga.
        if unit_type == "Section":

            if not parent_id_value.isdigit():
                connection.close()
                return "A Section must belong to an active Division.", 400

            new_parent_id = int(parent_id_value)

            parent_division = connection.execute("""
                SELECT id
                FROM organizational_units
                WHERE id = ?
                  AND unit_type = 'Division'
                  AND is_active = 1
            """, (new_parent_id,)).fetchone()

            if parent_division is None:
                connection.close()
                return "The selected parent must be an active Division.", 400

            # Section ko doosri Division mein move karne se pehle
            # ensure karein ke koi active employee us Section mein na ho.
            if new_parent_id != old_parent_id:

                active_employee_count = connection.execute("""
                    SELECT COUNT(*) AS total
                    FROM employee_location_assignments
                    WHERE section_id = ?
                      AND is_active = 1
                """, (unit_id,)).fetchone()["total"]

                active_head_count = connection.execute("""
                    SELECT COUNT(*) AS total
                    FROM section_head_assignments
                    WHERE section_id = ?
                      AND is_active = 1
                """, (unit_id,)).fetchone()["total"]

                if active_employee_count > 0:
                    connection.close()

                    return (
                        "This Section cannot be moved because it has "
                        f"{active_employee_count} active employee(s). "
                        "Transfer or remove those employees from the "
                        "Section first.",
                        400
                    )

                if active_head_count > 0:
                    connection.close()

                    return (
                        "This Section cannot be moved because it has "
                        "an active Head. End the Head responsibility first.",
                        400
                    )

        # Division aur Office Section ke child nahi honge.
        elif unit_type in ("Division", "Office"):
            new_parent_id = None

        # Purane legacy unit types ka parent automatically change nahi hoga.
        else:
            new_parent_id = old_parent_id

        # Duplicate name checking.
        if unit_type == "Section":

            existing_units = connection.execute("""
                SELECT id, name, is_active
                FROM organizational_units
                WHERE unit_type = 'Section'
                  AND parent_id = ?
                  AND id != ?
            """, (
                new_parent_id,
                unit_id
            )).fetchall()

        else:

            existing_units = connection.execute("""
                SELECT id, name, is_active
                FROM organizational_units
                WHERE unit_type = ?
                  AND id != ?
            """, (
                unit_type,
                unit_id
            )).fetchall()

        normalized_new_name = name.casefold()
        duplicate_unit = None

        for existing_unit in existing_units:

            existing_name = clean_name(
                existing_unit["name"]
            ).casefold()

            if existing_name == normalized_new_name:
                duplicate_unit = existing_unit
                break

        if duplicate_unit:

            connection.close()

            if duplicate_unit["is_active"] == 1:
                return (
                    f"Another {unit_type} named '{name}' already exists.",
                    400
                )

            return (
                f"An inactive {unit_type} named '{name}' already exists. "
                "Reactivate that unit instead of creating a duplicate name.",
                400
            )

        old_clean_name = clean_name(unit["name"])

        # Agar official name change hua hai to old history close karein.
        if old_clean_name != name:

            connection.execute("""
                UPDATE organizational_unit_name_history
                SET is_current = 0,
                    end_date = CURRENT_TIMESTAMP
                WHERE organizational_unit_id = ?
                  AND is_current = 1
            """, (unit_id,))

            connection.execute("""
                INSERT INTO organizational_unit_name_history
                (
                    organizational_unit_id,
                    name,
                    normalized_name,
                    start_date,
                    is_current
                )
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)
            """, (
                unit_id,
                name,
                normalized_new_name
            ))

        record_unit_parent(connection, unit_id, new_parent_id)

        # Current master record update karein.
        connection.execute("""
            UPDATE organizational_units
            SET name = ?,
                parent_id = ?
            WHERE id = ?
        """, (
            name,
            new_parent_id,
            unit_id
        ))

        connection.commit()
        connection.close()

        return redirect("/admin/units")

    # Section edit form ke liye active Divisions.
    parent_units = connection.execute("""
        SELECT id, name
        FROM organizational_units
        WHERE unit_type = 'Division'
          AND is_active = 1
          AND id != ?
        ORDER BY name
    """, (unit_id,)).fetchall()

    parent_history = connection.execute("""SELECT h.start_date,h.end_date,h.is_current,
        parent.name AS parent_name FROM organizational_unit_parent_history h
        LEFT JOIN organizational_units parent ON parent.id=h.parent_id
        WHERE h.organizational_unit_id=? ORDER BY h.id DESC""", (unit_id,)).fetchall()
    connection.close()

    return render_template(
        "edit_unit.html",
        unit=unit,
        parent_units=parent_units,
        parent_history=parent_history
    )
@app.route("/admin/units/deactivate/<int:unit_id>", methods=["POST"])
def deactivate_unit(unit_id):

    connection = get_db_connection()

    unit = connection.execute("""
        SELECT
            id,
            name,
            unit_type,
            parent_id,
            is_active
        FROM organizational_units
        WHERE id = ?
    """, (unit_id,)).fetchone()

    if unit is None:
        connection.close()
        return "Organizational unit not found.", 404

    if unit["is_active"] == 0:
        connection.close()
        return redirect("/admin/units")

    unit_type = unit["unit_type"]

    # =================================================
    # DIVISION DEACTIVATION
    # =================================================

    if unit_type == "Division":

        child_sections = connection.execute("""
            SELECT id
            FROM organizational_units
            WHERE unit_type = 'Section'
              AND parent_id = ?
        """, (unit_id,)).fetchall()

        child_section_ids = [
            section["id"]
            for section in child_sections
        ]

        # Division ke employees Without Division ho jayenge.
        # Unki Section bhi automatically end ho jayegi.
        connection.execute("""
            UPDATE employee_location_assignments
            SET is_active = 0,
                end_date = COALESCE(
                    end_date,
                    CURRENT_DATE
                )
            WHERE organizational_unit_id = ?
              AND is_active = 1
        """, (unit_id,))

        # Division ki reporting authority history close karein.
        connection.execute("""
            UPDATE division_reporting_assignments
            SET is_active = 0,
                end_date = COALESCE(
                    end_date,
                    CURRENT_DATE
                )
            WHERE division_id = ?
              AND is_active = 1
        """, (unit_id,))

        # Manager ya Acting Manager responsibility close karein.
        connection.execute("""
            UPDATE division_management_assignments
            SET is_active = 0,
                end_date = COALESCE(
                    end_date,
                    CURRENT_DATE
                )
            WHERE division_id = ?
              AND is_active = 1
        """, (unit_id,))

        # Division ke tamam Sections bhi inactive honge.
        if child_section_ids:

            placeholders = ",".join(
                "?"
                for section_id in child_section_ids
            )

            connection.execute(
                f"""
                UPDATE organizational_units
                SET is_active = 0
                WHERE id IN ({placeholders})
                """,
                child_section_ids
            )

            # Sections ke active Heads close karein.
            connection.execute(
                f"""
                UPDATE section_head_assignments
                SET is_active = 0,
                    end_date = COALESCE(
                        end_date,
                        CURRENT_DATE
                    )
                WHERE section_id IN ({placeholders})
                  AND is_active = 1
                """,
                child_section_ids
            )

        # Purane generic responsibility links bhi close karein.
        affected_unit_ids = [
            unit_id,
            *child_section_ids
        ]

        affected_placeholders = ",".join(
            "?"
            for affected_id in affected_unit_ids
        )

        connection.execute(
            f"""
            UPDATE post_assignment_units
            SET is_active = 0,
                end_date = COALESCE(
                    end_date,
                    CURRENT_DATE
                )
            WHERE organizational_unit_id
                  IN ({affected_placeholders})
              AND is_active = 1
            """,
            affected_unit_ids
        )

    # =================================================
    # SECTION DEACTIVATION
    # =================================================

    elif unit_type == "Section":

        affected_employees = connection.execute("""
            SELECT
                employee_id,
                organizational_unit_id
            FROM employee_location_assignments
            WHERE section_id = ?
              AND is_active = 1
        """, (unit_id,)).fetchall()

        # Purani Section assignment history close karein.
        connection.execute("""
            UPDATE employee_location_assignments
            SET is_active = 0,
                end_date = COALESCE(
                    end_date,
                    CURRENT_DATE
                )
            WHERE section_id = ?
              AND is_active = 1
        """, (unit_id,))

        # Employees same Division mein rahenge,
        # magar ab unki Section assigned nahi hogi.
        for employee_location in affected_employees:

            connection.execute("""
                INSERT INTO employee_location_assignments
                (
                    employee_id,
                    organizational_unit_id,
                    section_id,
                    start_date,
                    is_active
                )
                VALUES (?, ?, NULL, CURRENT_DATE, 1)
            """, (
                employee_location["employee_id"],
                employee_location["organizational_unit_id"]
            ))

        # Section Head responsibility close karein.
        connection.execute("""
            UPDATE section_head_assignments
            SET is_active = 0,
                end_date = COALESCE(
                    end_date,
                    CURRENT_DATE
                )
            WHERE section_id = ?
              AND is_active = 1
        """, (unit_id,))

        # Purana generic Head/unit responsibility link close karein.
        connection.execute("""
            UPDATE post_assignment_units
            SET is_active = 0,
                end_date = COALESCE(
                    end_date,
                    CURRENT_DATE
                )
            WHERE organizational_unit_id = ?
              AND is_active = 1
        """, (unit_id,))

    # =================================================
    # OFFICE OR LEGACY UNIT DEACTIVATION
    # =================================================

    else:

        # Office staff Without Division/Office ho jayega.
        connection.execute("""
            UPDATE employee_location_assignments
            SET is_active = 0,
                end_date = COALESCE(
                    end_date,
                    CURRENT_DATE
                )
            WHERE organizational_unit_id = ?
              AND is_active = 1
        """, (unit_id,))

        connection.execute("""
            UPDATE post_assignment_units
            SET is_active = 0,
                end_date = COALESCE(
                    end_date,
                    CURRENT_DATE
                )
            WHERE organizational_unit_id = ?
              AND is_active = 1
        """, (unit_id,))

    # Selected unit ko inactive karein.
    connection.execute("""
        UPDATE organizational_units
        SET is_active = 0
        WHERE id = ?
    """, (unit_id,))

    connection.commit()
    connection.close()

    return redirect("/admin/units")


@app.route("/admin/units/reactivate/<int:unit_id>", methods=["POST"])
def reactivate_unit(unit_id):

    connection = get_db_connection()

    unit = connection.execute("""
        SELECT
            id,
            name,
            unit_type,
            parent_id,
            is_active
        FROM organizational_units
        WHERE id = ?
    """, (unit_id,)).fetchone()

    if unit is None:
        connection.close()
        return "Organizational unit not found.", 404

    if unit["is_active"] == 1:
        connection.close()
        return redirect("/admin/units")

    unit_type = unit["unit_type"]

    # Section sirf active parent Division ke andar reactivate hogi.
    if unit_type == "Section":

        parent_division = connection.execute("""
            SELECT id
            FROM organizational_units
            WHERE id = ?
              AND unit_type = 'Division'
              AND is_active = 1
        """, (unit["parent_id"],)).fetchone()

        if parent_division is None:
            connection.close()

            return (
                "This Section cannot be reactivated because its "
                "parent Division is inactive. Reactivate the parent "
                "Division first.",
                400
            )

        comparable_units = connection.execute("""
            SELECT id, name
            FROM organizational_units
            WHERE unit_type = 'Section'
              AND parent_id = ?
              AND is_active = 1
              AND id != ?
        """, (
            unit["parent_id"],
            unit_id
        )).fetchall()

    else:

        comparable_units = connection.execute("""
            SELECT id, name
            FROM organizational_units
            WHERE unit_type = ?
              AND is_active = 1
              AND id != ?
        """, (
            unit_type,
            unit_id
        )).fetchall()

    normalized_unit_name = clean_name(
        unit["name"]
    ).casefold()

    for comparable_unit in comparable_units:

        comparable_name = clean_name(
            comparable_unit["name"]
        ).casefold()

        if comparable_name == normalized_unit_name:

            connection.close()

            return (
                f"Cannot reactivate '{unit['name']}' because an "
                f"active {unit_type} with the same name already exists.",
                400
            )

    connection.execute("""
        UPDATE organizational_units
        SET is_active = 1
        WHERE id = ?
    """, (unit_id,))

    connection.commit()
    connection.close()

    return redirect("/admin/units")



@app.route(
    "/admin/divisions/<int:division_id>/reporting-authority",
    methods=["GET", "POST"]
)
@organization_manager_required
def manage_division_reporting_authority(division_id):

    connection = get_db_connection()

    division = connection.execute("""
        SELECT
            id,
            name,
            is_active
        FROM organizational_units
        WHERE id = ?
          AND unit_type = 'Division'
    """, (division_id,)).fetchone()

    if division is None:
        connection.close()
        return "Division not found.", 404

    authority_posts_list = authority_posts(connection)

    current_assignment = connection.execute("""
        SELECT
            division_reporting_assignments.id,
            division_reporting_assignments.authority_post_id,
            posts.name AS authority_name,
            division_reporting_assignments.start_date
        FROM division_reporting_assignments

        JOIN posts
            ON division_reporting_assignments.authority_post_id
               = posts.id

        WHERE division_reporting_assignments.division_id = ?
          AND division_reporting_assignments.is_active = 1
    """, (division_id,)).fetchone()

    if request.method == "POST":
        if not session.get("reporting_csrf_token") or request.form.get("csrf_token") != session["reporting_csrf_token"]:
            connection.close()
            abort(400)


        authority_post_id_value = request.form.get(
            "authority_post_id",
            ""
        ).strip()

        if division["is_active"] == 0:
            connection.close()

            return (
                "Reporting authority cannot be assigned to an "
                "inactive Division.",
                400
            )

        if not authority_post_id_value.isdigit():
            connection.close()

            return (
                "Please select a reporting authority.",
                400
            )

        authority_post_id = int(authority_post_id_value)

        try:
            connection.execute("BEGIN IMMEDIATE")
            set_division_authority(connection, division_id, authority_post_id)
            connection.commit()
        except (ValueError, sqlite3.IntegrityError) as error:
            connection.rollback()
            connection.close()
            return str(error), 400
        connection.close()
        return redirect("/admin/units")

    reporting_history = connection.execute("""
        SELECT
            posts.name AS authority_name,
            division_reporting_assignments.start_date,
            division_reporting_assignments.end_date,
            division_reporting_assignments.is_active

        FROM division_reporting_assignments

        JOIN posts
            ON division_reporting_assignments.authority_post_id
               = posts.id

        WHERE division_reporting_assignments.division_id = ?

        ORDER BY division_reporting_assignments.id DESC
    """, (division_id,)).fetchall()

    connection.close()

    session.setdefault("reporting_csrf_token", secrets.token_hex(32))
    return render_template(
        "assign_division_authority.html",
        division=division,
        authority_posts=authority_posts_list,
        current_assignment=current_assignment,
        reporting_history=reporting_history
    )
# =================================================
# DIVISION MANAGER / ACTING MANAGER
# =================================================

@app.route(
    "/admin/divisions/<int:division_id>/management",
    methods=["GET", "POST"]
)
def manage_division_management(division_id):

    connection = get_db_connection()

    division = connection.execute("""
        SELECT
            id,
            name,
            is_active
        FROM organizational_units
        WHERE id = ?
          AND unit_type = 'Division'
    """, (division_id,)).fetchone()

    if division is None:
        connection.close()
        return "Division not found.", 404

    # Sirf woh active employees available honge jinke paas
    # active Manager ya Acting Manager post maujood hai.
    eligible_employees = connection.execute("""
        SELECT
            employees.id,
            employees.pin,
            employees.name,
            posts.name AS active_post,
            employee_post_assignments.id AS post_assignment_id
        FROM employees

        JOIN employee_post_assignments
            ON employee_post_assignments.employee_id
               = employees.id
           AND employee_post_assignments.is_active = 1

        JOIN posts
            ON employee_post_assignments.post_id
               = posts.id
           AND posts.is_active = 1

        WHERE employees.is_active = 1
          AND posts.name IN (
              'Manager',
              'Acting Manager'
          )

        ORDER BY
            employees.name,
            employees.pin
    """).fetchall()

    current_management = connection.execute("""
        SELECT
            division_management_assignments.id,
            division_management_assignments.employee_id,
            division_management_assignments.responsibility_type,
            division_management_assignments.is_primary,
            division_management_assignments.post_assignment_id,
            division_management_assignments.start_date,
            employees.pin,
            employees.name AS employee_name,
            posts.name AS active_post
        FROM division_management_assignments

        JOIN employees
            ON division_management_assignments.employee_id
               = employees.id

        LEFT JOIN employee_post_assignments
            ON division_management_assignments.post_assignment_id
               = employee_post_assignments.id

        LEFT JOIN posts
            ON employee_post_assignments.post_id
               = posts.id

        WHERE division_management_assignments.division_id = ?
          AND division_management_assignments.is_active = 1
    """, (division_id,)).fetchone()

    if request.method == "POST":

        employee_id_value = request.form.get(
            "employee_id",
            ""
        ).strip()

        responsibility_type = request.form.get(
            "responsibility_type",
            ""
        ).strip()

        if division["is_active"] == 0:
            connection.close()

            return (
                "Manager or Acting Manager cannot be assigned "
                "to an inactive Division.",
                400
            )

        if not employee_id_value.isdigit():
            connection.close()
            return "Please select an employee.", 400

        if responsibility_type not in (
            "Manager",
            "Acting Manager"
        ):
            connection.close()
            return "Please select a valid responsibility type.", 400

        employee_id = int(employee_id_value)

        selected_employee = connection.execute("""
            SELECT
                employees.id,
                employees.pin,
                employees.name,
                employee_post_assignments.id
                    AS post_assignment_id,
                posts.name AS active_post
            FROM employees

            JOIN employee_post_assignments
                ON employee_post_assignments.employee_id
                   = employees.id
               AND employee_post_assignments.is_active = 1

            JOIN posts
                ON employee_post_assignments.post_id
                   = posts.id
               AND posts.is_active = 1

            WHERE employees.id = ?
              AND employees.is_active = 1
              AND posts.name IN (
                  'Manager',
                  'Acting Manager'
              )
        """, (employee_id,)).fetchone()

        if selected_employee is None:
            connection.close()

            return (
                "The selected employee must have an active "
                "Manager or Acting Manager post.",
                400
            )

        active_post = selected_employee["active_post"]

        # Primary Manager responsibility ke liye employee ka
        # active post Manager hona lazmi hai.
        if (
            responsibility_type == "Manager"
            and active_post != "Manager"
        ):
            connection.close()

            return (
                "An employee with the Acting Manager post cannot "
                "be assigned as the primary Manager.",
                400
            )

        # Manager post holder apni primary Division ke ilawa
        # additional Divisions ka Acting Manager ban sakta hai.
        if (
            responsibility_type == "Acting Manager"
            and active_post not in (
                "Manager",
                "Acting Manager"
            )
        ):
            connection.close()
            return "Invalid Acting Manager assignment.", 400

        is_primary = (
            1
            if responsibility_type == "Manager"
            else 0
        )

        # Ek employee sirf ek Division ka primary Manager hoga.
        if responsibility_type == "Manager":

            other_primary_division = connection.execute("""
                SELECT
                    division_management_assignments.id,
                    organizational_units.name AS division_name
                FROM division_management_assignments

                JOIN organizational_units
                    ON division_management_assignments.division_id
                       = organizational_units.id

                WHERE division_management_assignments.employee_id = ?
                  AND division_management_assignments.is_active = 1
                  AND division_management_assignments.responsibility_type
                      = 'Manager'
                  AND division_management_assignments.is_primary = 1
                  AND division_management_assignments.division_id != ?
            """, (
                employee_id,
                division_id
            )).fetchone()

            if other_primary_division is not None:
                connection.close()

                return (
                    "This employee is already the primary Manager of "
                    f"{other_primary_division['division_name']}. "
                    "For an additional Division, select Acting Manager.",
                    400
                )

        # Bilkul same assignment dobara save ho to duplicate
        # history record create nahi hoga.
        if (
            current_management is not None
            and current_management["employee_id"] == employee_id
            and current_management["responsibility_type"]
                == responsibility_type
        ):
            connection.close()

            return redirect(
                f"/admin/divisions/{division_id}/management"
            )

        post_assignment_id = selected_employee[
            "post_assignment_id"
        ]

        try:

            # Division ke purane current incharge ko history mein
            # close karein.
            if current_management is not None:

                connection.execute("""
                    UPDATE division_management_assignments
                    SET is_active = 0,
                        end_date = COALESCE(
                            end_date,
                            CURRENT_DATE
                        )
                    WHERE id = ?
                """, (current_management["id"],))

                old_post_assignment_id = current_management[
                    "post_assignment_id"
                ]

                # Purana generic unit-responsibility link bhi close hoga.
                if old_post_assignment_id is not None:

                    connection.execute("""
                        UPDATE post_assignment_units
                        SET is_active = 0,
                            end_date = COALESCE(
                                end_date,
                                CURRENT_DATE
                            )
                        WHERE post_assignment_id = ?
                          AND organizational_unit_id = ?
                          AND is_active = 1
                    """, (
                        old_post_assignment_id,
                        division_id
                    ))

            # New Manager ya Acting Manager responsibility create karein.
            connection.execute("""
                INSERT INTO division_management_assignments
                (
                    employee_id,
                    division_id,
                    responsibility_type,
                    is_primary,
                    post_assignment_id,
                    start_date,
                    is_active
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_DATE, 1)
            """, (
                employee_id,
                division_id,
                responsibility_type,
                is_primary,
                post_assignment_id
            ))

            # Agar is post aur Division ka historical link pehle se hai
            # to usi ko reactivate karein.
            updated_link = connection.execute("""
                UPDATE post_assignment_units
                SET start_date = CURRENT_DATE,
                    end_date = NULL,
                    is_active = 1
                WHERE post_assignment_id = ?
                  AND organizational_unit_id = ?
            """, (
                post_assignment_id,
                division_id
            ))

            # Pehli baar responsibility mil rahi ho to new link banega.
            if updated_link.rowcount == 0:

                connection.execute("""
                    INSERT INTO post_assignment_units
                    (
                        post_assignment_id,
                        organizational_unit_id,
                        start_date,
                        is_active
                    )
                    VALUES (?, ?, CURRENT_DATE, 1)
                """, (
                    post_assignment_id,
                    division_id
                ))

            connection.commit()

        except sqlite3.IntegrityError as error:

            connection.rollback()
            connection.close()

            return (
                "This management responsibility could not be saved. "
                f"Database rule: {error}",
                400
            )

        connection.close()

        return redirect(
            f"/admin/divisions/{division_id}/management"
        )

    management_history = connection.execute("""
        SELECT
            division_management_assignments.id,
            division_management_assignments.responsibility_type,
            division_management_assignments.start_date,
            division_management_assignments.end_date,
            division_management_assignments.is_active,
            employees.pin,
            employees.name AS employee_name
        FROM division_management_assignments

        JOIN employees
            ON division_management_assignments.employee_id
               = employees.id

        WHERE division_management_assignments.division_id = ?

        ORDER BY
            division_management_assignments.is_active DESC,
            division_management_assignments.id DESC
    """, (division_id,)).fetchall()

    connection.close()

    return render_template(
        "assign_division_management.html",
        division=division,
        eligible_employees=eligible_employees,
        current_management=current_management,
        management_history=management_history
    )

# =================================================
# SECTION HEAD
# =================================================

@app.route(
    "/admin/sections/<int:section_id>/head",
    methods=["GET", "POST"]
)
def manage_section_head(section_id):

    connection = get_db_connection()

    section = connection.execute("""
        SELECT
            section.id,
            section.name,
            section.parent_id,
            section.is_active,
            division.name AS division_name,
            division.is_active AS division_is_active
        FROM organizational_units AS section

        JOIN organizational_units AS division
            ON section.parent_id = division.id
           AND division.unit_type = 'Division'

        WHERE section.id = ?
          AND section.unit_type = 'Section'
    """, (section_id,)).fetchone()

    if section is None:
        connection.close()
        return "Section not found.", 404

    # Sirf woh employees eligible honge:
    # 1. Jinke paas active Head post ho.
    # 2. Jo isi Section ki parent Division mein posted hon.
    eligible_employees = connection.execute("""
        SELECT
            employees.id,
            employees.pin,
            employees.name,
            employee_post_assignments.id
                AS post_assignment_id,
            posts.name AS active_post,
            employee_section.name AS home_section
        FROM employees

        JOIN employee_post_assignments
            ON employee_post_assignments.employee_id
               = employees.id
           AND employee_post_assignments.is_active = 1

        JOIN posts
            ON employee_post_assignments.post_id
               = posts.id
           AND posts.is_active = 1
           AND posts.name = 'Head'

        JOIN employee_location_assignments
            ON employee_location_assignments.employee_id
               = employees.id
           AND employee_location_assignments.is_active = 1
           AND employee_location_assignments.organizational_unit_id
               = ?

        LEFT JOIN organizational_units AS employee_section
            ON employee_location_assignments.section_id
               = employee_section.id

        WHERE employees.is_active = 1

        ORDER BY
            employees.name,
            employees.pin
    """, (section["parent_id"],)).fetchall()

    current_head = connection.execute("""
        SELECT
            section_head_assignments.id,
            section_head_assignments.employee_id,
            section_head_assignments.post_assignment_id,
            section_head_assignments.start_date,
            employees.pin,
            employees.name AS employee_name,
            posts.name AS active_post
        FROM section_head_assignments

        JOIN employees
            ON section_head_assignments.employee_id
               = employees.id

        LEFT JOIN employee_post_assignments
            ON section_head_assignments.post_assignment_id
               = employee_post_assignments.id

        LEFT JOIN posts
            ON employee_post_assignments.post_id
               = posts.id

        WHERE section_head_assignments.section_id = ?
          AND section_head_assignments.is_active = 1
    """, (section_id,)).fetchone()

    if request.method == "POST":

        employee_id_value = request.form.get(
            "employee_id",
            ""
        ).strip()

        if section["is_active"] == 0:
            connection.close()

            return (
                "A Head cannot be assigned to an inactive Section.",
                400
            )

        if section["division_is_active"] == 0:
            connection.close()

            return (
                "A Head cannot be assigned because the parent "
                "Division is inactive.",
                400
            )

        if not employee_id_value.isdigit():
            connection.close()
            return "Please select an employee.", 400

        employee_id = int(employee_id_value)

        # Backend dobara tamam eligibility rules validate karega.
        selected_employee = connection.execute("""
            SELECT
                employees.id,
                employees.pin,
                employees.name,
                employee_post_assignments.id
                    AS post_assignment_id,
                posts.name AS active_post
            FROM employees

            JOIN employee_post_assignments
                ON employee_post_assignments.employee_id
                   = employees.id
               AND employee_post_assignments.is_active = 1

            JOIN posts
                ON employee_post_assignments.post_id
                   = posts.id
               AND posts.is_active = 1
               AND posts.name = 'Head'

            JOIN employee_location_assignments
                ON employee_location_assignments.employee_id
                   = employees.id
               AND employee_location_assignments.is_active = 1
               AND employee_location_assignments.organizational_unit_id
                   = ?

            WHERE employees.id = ?
              AND employees.is_active = 1
        """, (
            section["parent_id"],
            employee_id
        )).fetchone()

        if selected_employee is None:
            connection.close()

            return (
                "The selected employee must have an active Head post "
                "and must be posted in this Section's parent Division.",
                400
            )

        # Same Head dobara save ho to duplicate history nahi banegi.
        if (
            current_head is not None
            and current_head["employee_id"] == employee_id
        ):
            connection.close()

            return redirect(
                f"/admin/sections/{section_id}/head"
            )

        post_assignment_id = selected_employee[
            "post_assignment_id"
        ]

        try:

            # Purane current Head ko history mein close karein.
            if current_head is not None:

                connection.execute("""
                    UPDATE section_head_assignments
                    SET is_active = 0,
                        end_date = COALESCE(
                            end_date,
                            CURRENT_DATE
                        )
                    WHERE id = ?
                """, (current_head["id"],))

                old_post_assignment_id = current_head[
                    "post_assignment_id"
                ]

                # Purana generic Section responsibility link close karein.
                if old_post_assignment_id is not None:

                    connection.execute("""
                        UPDATE post_assignment_units
                        SET is_active = 0,
                            end_date = COALESCE(
                                end_date,
                                CURRENT_DATE
                            )
                        WHERE post_assignment_id = ?
                          AND organizational_unit_id = ?
                          AND is_active = 1
                    """, (
                        old_post_assignment_id,
                        section_id
                    ))

            # Naya current Head assignment create karein.
            connection.execute("""
                INSERT INTO section_head_assignments
                (
                    employee_id,
                    section_id,
                    post_assignment_id,
                    start_date,
                    is_active
                )
                VALUES (?, ?, ?, CURRENT_DATE, 1)
            """, (
                employee_id,
                section_id,
                post_assignment_id
            ))

            # Historical generic link pehle se ho to reactivate karein.
            updated_link = connection.execute("""
                UPDATE post_assignment_units
                SET start_date = CURRENT_DATE,
                    end_date = NULL,
                    is_active = 1
                WHERE post_assignment_id = ?
                  AND organizational_unit_id = ?
            """, (
                post_assignment_id,
                section_id
            ))

            # Pehli assignment ho to new responsibility link banega.
            if updated_link.rowcount == 0:

                connection.execute("""
                    INSERT INTO post_assignment_units
                    (
                        post_assignment_id,
                        organizational_unit_id,
                        start_date,
                        is_active
                    )
                    VALUES (?, ?, CURRENT_DATE, 1)
                """, (
                    post_assignment_id,
                    section_id
                ))

            connection.commit()

        except sqlite3.IntegrityError as error:

            connection.rollback()
            connection.close()

            return (
                "This Head responsibility could not be saved. "
                f"Database rule: {error}",
                400
            )

        connection.close()

        return redirect(
            f"/admin/sections/{section_id}/head"
        )

    head_history = connection.execute("""
        SELECT
            section_head_assignments.id,
            section_head_assignments.start_date,
            section_head_assignments.end_date,
            section_head_assignments.is_active,
            employees.pin,
            employees.name AS employee_name
        FROM section_head_assignments

        JOIN employees
            ON section_head_assignments.employee_id
               = employees.id

        WHERE section_head_assignments.section_id = ?

        ORDER BY
            section_head_assignments.is_active DESC,
            section_head_assignments.id DESC
    """, (section_id,)).fetchall()

    connection.close()

    return render_template(
        "assign_section_head.html",
        section=section,
        eligible_employees=eligible_employees,
        current_head=current_head,
        head_history=head_history
    )


# -------------------------------------------------
# DESIGNATIONS
# -------------------------------------------------

# View all designations
@app.route("/admin/designations")
def manage_designations():

    connection = get_db_connection()

    designations = connection.execute("""
        SELECT id, name, is_active
        FROM designations
        ORDER BY id DESC
    """).fetchall()

    connection.close()

    return render_template(
        "designations.html",
        designations=designations
    )


# Add new designation
@app.route("/admin/designations/add", methods=["GET", "POST"])
def add_designation():

    if request.method == "POST":

        # Extra spaces remove kar do
        name = " ".join(request.form["name"].split())

        connection = get_db_connection()

        # Check karo designation pehle se mojood to nahi
        existing_designation = connection.execute("""
            SELECT id
            FROM designations
            WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))
        """, (name,)).fetchone()

        if existing_designation:

            connection.close()

            return """
                <h2>Designation already exists!</h2>
                <p>This designation has already been added.</p>
                <a href="/admin/designations/add">Go Back</a>
            """, 400

        # Duplicate nahi hai to save karo
        connection.execute("""
            INSERT INTO designations (name)
            VALUES (?)
        """, (name,))

        connection.commit()
        connection.close()

        return redirect("/admin/designations")

    return render_template("add_designation.html")

    if request.method == "POST":

        name = request.form["name"]

        connection = get_db_connection()

        connection.execute("""
            INSERT INTO designations (name)
            VALUES (?)
        """, (name,))

        connection.commit()
        connection.close()

        return redirect("/admin/designations")

    return render_template("add_designation.html")

# -------------------------------------------------
# EMPLOYEES
# -------------------------------------------------

# View all employees
@app.route("/admin/employees")
def manage_employees():

    search = clean_name(
        request.args.get("search", "")
    )

    connection = get_db_connection()

    query = """
        SELECT
            employees.id,
            employees.pin,
            employees.name,
            employees.extension_number,
            employees.is_active,

            designation.name AS designation_name,

            home_unit.name AS unit_name,
            home_unit.unit_type AS unit_type,

            section.name AS section_name,

            post.name AS post_name

        FROM employees

        LEFT JOIN employee_designation_assignments
            AS designation_assignment

            ON designation_assignment.employee_id
               = employees.id
           AND designation_assignment.is_active = 1

        LEFT JOIN designations AS designation
            ON designation_assignment.designation_id
               = designation.id

        LEFT JOIN employee_location_assignments
            AS location_assignment

            ON location_assignment.employee_id
               = employees.id
           AND location_assignment.is_active = 1

        LEFT JOIN organizational_units AS home_unit
            ON location_assignment.organizational_unit_id
               = home_unit.id

        LEFT JOIN organizational_units AS section
            ON location_assignment.section_id
               = section.id

        LEFT JOIN employee_post_assignments
            AS post_assignment

            ON post_assignment.employee_id
               = employees.id
           AND post_assignment.is_active = 1

        LEFT JOIN posts AS post
            ON post_assignment.post_id = post.id
    """

    parameters = []

    if search:

        search_value = f"%{search}%"

        query += """
            WHERE employees.pin LIKE ?
               OR employees.name LIKE ?
               OR designation.name LIKE ?
               OR home_unit.name LIKE ?
               OR section.name LIKE ?
               OR post.name LIKE ?
               OR employees.extension_number LIKE ?
        """

        parameters = [
            search_value,
            search_value,
            search_value,
            search_value,
            search_value,
            search_value,
            search_value
        ]

    query += """
        ORDER BY
            employees.is_active DESC,
            employees.name
    """

    employees = connection.execute(
        query,
        parameters
    ).fetchall()

    connection.close()

    return render_template(
        "employees.html",
        employees=employees,
        search=search
    )

# Add new employee
@app.route("/admin/employees/add", methods=["GET", "POST"])
def add_employee():

    connection = get_db_connection()

    if request.method == "POST":

        pin = request.form.get("pin", "").strip()
        name = clean_name(
            request.form.get("name", "")
        )

        designation_id_value = request.form.get(
            "designation_id",
            ""
        ).strip()

        organizational_unit_id_value = request.form.get(
            "organizational_unit_id",
            ""
        ).strip()

        section_id_value = request.form.get(
            "section_id",
            ""
        ).strip()

        extension_number = request.form.get(
            "extension_number",
            ""
        ).strip()

        # PIN sirf digits par mushtamil hoga.
        # Leading zero preserve rahega kyunki PIN TEXT hai.
        if not pin or not pin.isdigit():
            connection.close()
            return "PIN must contain digits only.", 400

        if not name:
            connection.close()
            return "Employee name is required.", 400

        # Duplicate PIN active ya inactive kisi employee ka nahi ho sakta.
        existing_pin = connection.execute("""
            SELECT id
            FROM employees
            WHERE pin = ?
        """, (pin,)).fetchone()

        if existing_pin:
            connection.close()
            return "An employee with this PIN already exists.", 400

        if not designation_id_value.isdigit():
            connection.close()
            return "Please select a valid designation.", 400

        designation_id = int(designation_id_value)

        designation = connection.execute("""
            SELECT id
            FROM designations
            WHERE id = ?
              AND is_active = 1
        """, (designation_id,)).fetchone()

        if designation is None:
            connection.close()
            return "The selected designation is not active.", 400

        if not organizational_unit_id_value.isdigit():
            connection.close()
            return "Please select an active Division or Office.", 400

        organizational_unit_id = int(
            organizational_unit_id_value
        )

        organizational_unit = connection.execute("""
            SELECT
                id,
                name,
                unit_type
            FROM organizational_units
            WHERE id = ?
              AND unit_type IN (
                  'Division',
                  'Office'
              )
              AND is_active = 1
        """, (organizational_unit_id,)).fetchone()

        if organizational_unit is None:
            connection.close()
            return "Please select an active Division or Office.", 400

        section_id = None

        if section_id_value:

            if not section_id_value.isdigit():
                connection.close()
                return "Please select a valid Section.", 400

            section_id = int(section_id_value)

            section = connection.execute("""
                SELECT id
                FROM organizational_units
                WHERE id = ?
                  AND unit_type = 'Section'
                  AND parent_id = ?
                  AND is_active = 1
            """, (
                section_id,
                organizational_unit_id
            )).fetchone()

            if section is None:
                connection.close()

                return (
                    "The selected Section does not belong to the "
                    "selected Division.",
                    400
                )

        # Office employee ki Section nahi ho sakti.
        if (
            organizational_unit["unit_type"] == "Office"
            and section_id is not None
        ):
            connection.close()

            return (
                "An Office employee cannot be assigned to a Section.",
                400
            )

        try:

            # Legacy current columns abhi compatibility ke liye
            # maintain kiye ja rahe hain.
            cursor = connection.execute("""
                INSERT INTO employees
                (
                    pin,
                    name,
                    designation_id,
                    organizational_unit_id,
                    extension_number
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                pin,
                name,
                designation_id,
                organizational_unit_id,
                extension_number
            ))

            employee_id = cursor.lastrowid

            # Current designation ko history table mein save karein.
            connection.execute("""
                INSERT INTO employee_designation_assignments
                (
                    employee_id,
                    designation_id,
                    start_date,
                    is_active
                )
                VALUES (?, ?, CURRENT_DATE, 1)
            """, (
                employee_id,
                designation_id
            ))

            # Current Division/Office aur optional Section save karein.
            connection.execute("""
                INSERT INTO employee_location_assignments
                (
                    employee_id,
                    organizational_unit_id,
                    section_id,
                    start_date,
                    is_active
                )
                VALUES (?, ?, ?, CURRENT_DATE, 1)
            """, (
                employee_id,
                organizational_unit_id,
                section_id
            ))

            connection.commit()
            connection.close()

            return redirect("/admin/employees")

        except sqlite3.IntegrityError:

            connection.rollback()
            connection.close()

            return (
                "Employee could not be created because one of the "
                "selected values conflicts with an existing record.",
                400
            )

    designations = connection.execute("""
        SELECT id, name
        FROM designations
        WHERE is_active = 1
        ORDER BY name
    """).fetchall()

    units = connection.execute("""
        SELECT
            id,
            name,
            unit_type
        FROM organizational_units
        WHERE unit_type IN (
            'Division',
            'Office'
        )
          AND is_active = 1
        ORDER BY
            CASE unit_type
                WHEN 'Division' THEN 1
                WHEN 'Office' THEN 2
            END,
            name
    """).fetchall()

    sections = connection.execute("""
        SELECT
            section.id,
            section.name,
            section.parent_id
        FROM organizational_units AS section

        JOIN organizational_units AS parent_division
            ON section.parent_id = parent_division.id

        WHERE section.unit_type = 'Section'
          AND section.is_active = 1
          AND parent_division.unit_type = 'Division'
          AND parent_division.is_active = 1

        ORDER BY section.name
    """).fetchall()

    connection.close()

    return render_template(
        "add_employee.html",
        designations=designations,
        units=units,
        sections=sections
    )


# Delete designation only if it is not assigned to any employee
@app.route("/admin/designations/delete/<int:designation_id>", methods=["POST"])
def delete_designation(designation_id):

    connection = get_db_connection()

    # Pehle check karo ye designation kisi employee ko assigned hai ya nahi
    employee_count = connection.execute("""
        SELECT COUNT(*) AS total
        FROM employees
        WHERE designation_id = ?
    """, (designation_id,)).fetchone()["total"]

    # Agar employees use kar rahe hain to deletion block kar do
    if employee_count > 0:

        connection.close()

        return f"""
            <h2>Designation cannot be deleted</h2>
            <p>
                This designation is currently assigned to
                {employee_count} employee(s).
            </p>
            <p>
                Change those employees' designations first,
                or deactivate this designation instead.
            </p>
            <a href="/admin/designations">Go Back</a>
        """, 400

    # Agar koi employee use nahi kar raha to delete kar do
    connection.execute("""
        DELETE FROM designations
        WHERE id = ?
    """, (designation_id,))

    connection.commit()
    connection.close()

    return redirect("/admin/designations")


# -------------------------------------------------
# DVD REQUESTS
# -------------------------------------------------


# =================================================
# NEW DVD REQUEST
# =================================================

@app.route("/dvd-request/new", methods=["GET", "POST"])
def new_dvd_request():

    connection = get_db_connection()

    try:
        account = connection.execute("""
            SELECT employee_id
            FROM user_accounts
            WHERE id = ?
              AND is_active = 1
        """, (
            session["user_account_id"],
        )).fetchone()

        if account is None:
            abort(403)

        current_employee_id = account["employee_id"]

        employees = connection.execute("""
            SELECT
                employees.id,
                employees.pin,
                employees.name,
                employees.extension_number,
                designations.name AS designation_name,
                organizational_units.name AS unit_name

            FROM employees

            JOIN designations
                ON employees.designation_id = designations.id

            JOIN employee_location_assignments AS location
                ON location.employee_id = employees.id
               AND location.is_active = 1

            JOIN organizational_units
                ON location.organizational_unit_id =
                   organizational_units.id
               AND organizational_units.is_active = 1

            WHERE employees.is_active = 1
              AND employees.id = ?

            ORDER BY employees.name
        """, (current_employee_id,)).fetchall()

        if request.method == "POST":

            requester_id = request.form.get(
                "requester_employee_id", ""
            ).strip()

            dvd_category = request.form.get(
                "dvd_category", ""
            ).strip()

            permanent_source_type = request.form.get(
                "permanent_source_type", ""
            ).strip()

            # Only the logged-in employee can request media.
            if (
                not requester_id.isdigit()
                or int(requester_id) != current_employee_id
                or not employees
            ):
                return (
                    "Requests must use your own active "
                    "employee placement.",
                    400
                )

            allowed_categories = (
                "Internal",
                "Internet",
                "External",
                "Vendor",
                "Outward",
                "Permanent"
            )

            if dvd_category not in allowed_categories:
                return "Select a valid DVD category.", 400

            if dvd_category == "Permanent":

                if permanent_source_type not in (
                    "Internal",
                    "Internet",
                    "External",
                    "Vendor"
                ):
                    return (
                        "Permanent source type is required.",
                        400
                    )

            else:
                permanent_source_type = None

            # Multiple request items from the HTML form.
            descriptions = request.form.getlist(
                "description[]"
            )

            quantities = request.form.getlist(
                "quantity[]"
            )

            remarks_list = request.form.getlist(
                "remarks[]"
            )

            # Existing simple form compatibility:
            # Until the updated HTML is installed,
            # requests without item rows still work.
            has_item_fields = any((
                descriptions,
                quantities,
                remarks_list
            ))

            validated_items = []

            if has_item_fields:

                if not (
                    len(descriptions)
                    == len(quantities)
                    == len(remarks_list)
                ):
                    return (
                        "Request item fields do not match.",
                        400
                    )

                if not 1 <= len(descriptions) <= 20:
                    return (
                        "Add between 1 and 20 request items.",
                        400
                    )

                for index, description in enumerate(
                    descriptions, start=1
                ):

                    description = description.strip()

                    quantity_text = quantities[
                        index - 1
                    ].strip()

                    remarks = remarks_list[
                        index - 1
                    ].strip()

                    if not description:
                        return (
                            f"Description is required "
                            f"for item {index}.",
                            400
                        )

                    if len(description) > 1000:
                        return (
                            f"Description is too long "
                            f"for item {index}.",
                            400
                        )

                    if not quantity_text.isdigit():
                        return (
                            f"Invalid quantity for "
                            f"item {index}.",
                            400
                        )

                    quantity = int(quantity_text)

                    if not 1 <= quantity <= 1000:
                        return (
                            f"Quantity must be between "
                            f"1 and 1000 for item {index}.",
                            400
                        )

                    if len(remarks) > 1000:
                        return (
                            f"Remarks are too long "
                            f"for item {index}.",
                            400
                        )

                    validated_items.append((
                        description,
                        quantity,
                        remarks or None
                    ))

            # One database transaction:
            # either everything saves, or nothing saves.
            try:

                cursor = connection.execute("""
                    INSERT INTO dvd_requests
                    (
                        requester_employee_id,
                        dvd_category,
                        permanent_source_type
                    )
                    VALUES (?, ?, ?)
                """, (
                    current_employee_id,
                    dvd_category,
                    permanent_source_type
                ))

                request_id = cursor.lastrowid

                for (
                    description,
                    quantity,
                    remarks
                ) in validated_items:

                    connection.execute("""
                        INSERT INTO dvd_request_items
                        (
                            request_id,
                            description,
                            quantity,
                            remarks
                        )
                        VALUES (?, ?, ?, ?)
                    """, (
                        request_id,
                        description,
                        quantity,
                        remarks
                    ))

                connection.commit()

            except sqlite3.Error:

                connection.rollback()
                app.logger.exception(
                    "DVD request could not be saved"
                )

                return (
                    "Unable to save DVD request. "
                    "No partial request was saved.",
                    500
                )

            return redirect(
                f"/dvd-request/{request_id}"
            )

        return render_template(
            "new_dvd_request.html",
            employees=employees
        )

    finally:
        connection.close()




# =================================================
# CD/DVD - MY REQUESTS
# =================================================


# =================================================
# CD/DVD - PENDING APPROVALS (READ ONLY)
# =================================================

@app.route("/dvd-requests/pending")
@dvd_approval_access_required
def pending_dvd_approvals():

    connection = get_db_connection()

    try:
        account = connection.execute("""
            SELECT employee_id
            FROM user_accounts
            WHERE id = ?
              AND is_active = 1
        """, (session["user_account_id"],)).fetchone()

        if account is None:
            abort(403)

        employee_id = account["employee_id"]

        can_manage = account_has_permission(
            "dvd.request.manager_approve"
        )
        can_cyber = account_has_permission(
            "dvd.request.cyber_review"
        )
        can_it = account_has_permission(
            "dvd.request.technical_process"
        )

        # Manager/Head: only their active responsible
        # Division or Section, excluding own requests.
        manager_requests = []

        if can_manage:
            manager_requests = connection.execute("""
                SELECT DISTINCT
                    r.id,
                    r.dvd_category,
                    r.status,
                    r.created_at,
                    e.name AS requester_name,
                    e.pin AS requester_pin
                FROM dvd_requests AS r
                JOIN employees AS e
                    ON e.id = r.requester_employee_id
                JOIN employee_location_assignments AS loc
                    ON loc.employee_id = e.id
                   AND loc.is_active = 1
                WHERE r.status = 'Submitted'
                  AND r.requester_employee_id != ?
                  AND (
                    EXISTS (
                        SELECT 1
                        FROM division_management_assignments AS m
                        WHERE m.employee_id = ?
                          AND m.is_active = 1
                          AND m.division_id = loc.organizational_unit_id
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM section_head_assignments AS h
                        WHERE h.employee_id = ?
                          AND h.is_active = 1
                          AND h.section_id = loc.section_id
                    )
                  )
                ORDER BY r.id DESC
            """, (
                employee_id,
                employee_id,
                employee_id
            )).fetchall()

        # Cyber Security queue opens after Manager approval.
        cyber_requests = []

        if can_cyber:
            cyber_requests = connection.execute("""
                SELECT
                    r.id,
                    r.dvd_category,
                    r.status,
                    r.created_at,
                    e.name AS requester_name,
                    e.pin AS requester_pin
                FROM dvd_requests AS r
                JOIN employees AS e
                    ON e.id = r.requester_employee_id
                WHERE r.status = 'Manager Approved'
                  AND r.requester_employee_id != ?
                ORDER BY r.id DESC
            """, (employee_id,)).fetchall()

        # IT receives requests after physical SD
        # approval has been recorded.
        it_requests = []

        if can_it:
            it_requests = connection.execute("""
                SELECT
                    r.id,
                    r.dvd_category,
                    r.status,
                    r.created_at,
                    e.name AS requester_name,
                    e.pin AS requester_pin
                FROM dvd_requests AS r
                JOIN employees AS e
                    ON e.id = r.requester_employee_id
                WHERE r.status IN ('Cyber Approved', 'SD Approved')
                ORDER BY r.id DESC
            """).fetchall()

    finally:
        connection.close()

    session["dvd_approval_csrf_token"] = secrets.token_urlsafe(32)

    return render_template(
        "pending_dvd_approvals.html",
        manager_requests=manager_requests,
        cyber_requests=cyber_requests,
        it_requests=it_requests
    )


# =================================================
# CD/DVD - MANAGER DECISIONS (DEMO ONLY)
# =================================================

@app.route("/dvd-request/<int:request_id>/manager-decision", methods=["POST"])
@dvd_approval_access_required
def manager_dvd_decision(request_id):
    # Protect the real office database while the workflow is being tested.
    if os.path.basename(app.config["DATABASE"]).lower() != "office_demo.db":
        abort(403)

    if not account_has_permission("dvd.request.manager_approve"):
        abort(403)

    token = request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(
        token, session.get("dvd_approval_csrf_token", "")
    ):
        abort(400)

    decision = request.form.get("decision", "")
    if decision not in ("approve", "reject"):
        abort(400)

    connection = get_db_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        account = connection.execute("""
            SELECT employee_id FROM user_accounts
            WHERE id=? AND is_active=1
        """, (session["user_account_id"],)).fetchone()
        if account is None:
            abort(403)

        actor_id = account["employee_id"]
        dvd = connection.execute("""
            SELECT r.id, r.status, r.requester_employee_id,
                   EXISTS (
                       SELECT 1 FROM employee_location_assignments AS loc
                       WHERE loc.employee_id=r.requester_employee_id
                         AND loc.is_active=1
                         AND (
                             EXISTS (
                                 SELECT 1 FROM division_management_assignments AS m
                                 WHERE m.employee_id=? AND m.is_active=1
                                   AND m.division_id=loc.organizational_unit_id
                             )
                             OR EXISTS (
                                 SELECT 1 FROM section_head_assignments AS h
                                 WHERE h.employee_id=? AND h.is_active=1
                                   AND h.section_id=loc.section_id
                             )
                         )
                   ) AS responsible
            FROM dvd_requests AS r WHERE r.id=?
        """, (actor_id, actor_id, request_id)).fetchone()

        if dvd is None:
            abort(404)
        if (dvd["requester_employee_id"] == actor_id
                or not dvd["responsible"]):
            abort(403)
        if dvd["status"] != "Submitted":
            abort(409)

        # Audit table is introduced safely and only on the fictional demo DB.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS dvd_approval_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                actor_employee_id INTEGER NOT NULL,
                stage TEXT NOT NULL,
                decision TEXT NOT NULL,
                from_status TEXT NOT NULL,
                to_status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(request_id) REFERENCES dvd_requests(id),
                FOREIGN KEY(actor_employee_id) REFERENCES employees(id)
            )
        """)
        new_status = "Manager Approved" if decision == "approve" else "Manager Rejected"
        changed = connection.execute("""
            UPDATE dvd_requests SET status=?
            WHERE id=? AND status='Submitted'
        """, (new_status, request_id))
        if changed.rowcount != 1:
            abort(409)
        connection.execute("""
            INSERT INTO dvd_approval_history
            (request_id,actor_employee_id,stage,decision,from_status,to_status)
            VALUES (?,?,'Manager',?,'Submitted',?)
        """, (request_id, actor_id, decision, new_status))
        connection.commit()
    finally:
        connection.close()

    return redirect("/dvd-requests/pending")

# =================================================
# CD/DVD - CYBER SECURITY DECISIONS (DEMO ONLY)
# =================================================

@app.route("/dvd-request/<int:request_id>/cyber-decision", methods=["POST"])
@dvd_approval_access_required
def cyber_dvd_decision(request_id):
    # Never enable through filename alone: validate marker inside demo DB.
    if os.path.basename(app.config["DATABASE"]).lower() != "office_demo.db":
        abort(403)
    if not account_has_permission("dvd.request.cyber_review"):
        abort(403)

    token = request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(
        token, session.get("dvd_approval_csrf_token", "")
    ):
        abort(400)
    decision = request.form.get("decision", "")
    if decision not in ("approve", "reject"):
        abort(400)

    connection = get_db_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        marker_table = connection.execute("""
            SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_metadata'
        """).fetchone()
        if not marker_table or not connection.execute("""
            SELECT 1 FROM demo_metadata WHERE marker='OMS_DEMO_V1'
        """).fetchone():
            abort(403)

        account = connection.execute("""
            SELECT employee_id FROM user_accounts
            WHERE id=? AND is_active=1
        """, (session["user_account_id"],)).fetchone()
        if account is None:
            abort(403)
        actor_id = account["employee_id"]

        dvd = connection.execute("""
            SELECT requester_employee_id, status FROM dvd_requests WHERE id=?
        """, (request_id,)).fetchone()
        if dvd is None:
            abort(404)
        if dvd["requester_employee_id"] == actor_id:
            abort(403)
        if dvd["status"] != 'Manager Approved':
            abort(409)

        # History table was created by the demo Manager decision flow.
        table = connection.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='dvd_approval_history'
        """).fetchone()
        if table is None:
            abort(409)

        new_status = ('Cyber Approved' if decision == 'approve'
                      else 'Cyber Rejected')
        changed = connection.execute("""
            UPDATE dvd_requests SET status=?
            WHERE id=? AND status='Manager Approved'
        """, (new_status, request_id))
        if changed.rowcount != 1:
            abort(409)
        connection.execute("""
            INSERT INTO dvd_approval_history
                (request_id,actor_employee_id,stage,decision,from_status,to_status)
            VALUES (?,?,'Cyber Security',?,'Manager Approved',?)
        """, (request_id, actor_id, decision, new_status))
        connection.commit()
    finally:
        connection.close()
    return redirect('/dvd-requests/pending')

# =================================================
# CD/DVD - RECORD PHYSICAL SD SIGNATURE (DEMO ONLY)
# =================================================

@app.route("/dvd-request/<int:request_id>/sd-paper-verified", methods=["POST"])
@dvd_approval_access_required
def record_sd_paper_verification(request_id):
    # This is NOT a digital SD approval. IT staff records that a
    # physically signed paper form was checked before IT processing.
    if os.path.basename(app.config["DATABASE"]).lower() != "office_demo.db":
        abort(403)
    if not account_has_permission("dvd.request.technical_process"):
        abort(403)

    token = request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(
        token, session.get("dvd_approval_csrf_token", "")
    ):
        abort(400)
    if request.form.get("paper_checked") != "yes":
        abort(400)

    connection = get_db_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        has_demo_table = connection.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='demo_metadata'
        """).fetchone()
        if not has_demo_table or not connection.execute("""
            SELECT 1 FROM demo_metadata WHERE marker='OMS_DEMO_V1'
        """).fetchone():
            abort(403)
        account = connection.execute("""
            SELECT employee_id FROM user_accounts
            WHERE id=? AND is_active=1
        """, (session["user_account_id"],)).fetchone()
        if account is None:
            abort(403)
        actor_id = account["employee_id"]
        dvd = connection.execute("""
            SELECT requester_employee_id, status
            FROM dvd_requests WHERE id=?
        """, (request_id,)).fetchone()
        if dvd is None:
            abort(404)
        if dvd["requester_employee_id"] == actor_id:
            abort(403)
        if dvd["status"] != "Cyber Approved":
            abort(409)
        if not connection.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='dvd_approval_history'
        """).fetchone():
            abort(409)
        changed = connection.execute("""
            UPDATE dvd_requests SET status='SD Approved'
            WHERE id=? AND status='Cyber Approved'
        """, (request_id,))
        if changed.rowcount != 1:
            abort(409)
        connection.execute("""
            INSERT INTO dvd_approval_history
                (request_id, actor_employee_id, stage, decision,
                 from_status, to_status)
            VALUES (?, ?, 'Physical SD Form Verification',
                    'paper_verified', 'Cyber Approved', 'SD Approved')
        """, (request_id, actor_id))
        connection.commit()
    finally:
        connection.close()
    return redirect('/dvd-requests/pending')

# =================================================
# CD/DVD - IT ISSUE ALL REQUESTED DISCS (DEMO ONLY)
# =================================================

@app.route("/dvd-request/<int:request_id>/issue-discs", methods=["POST"])
@dvd_approval_access_required
def issue_demo_dvds(request_id):
    # Demo feature, not approved for production.
    if os.path.basename(app.config["DATABASE"]).lower() != "office_demo.db":
        abort(403)
    if not account_has_permission("dvd.request.technical_process"):
        abort(403)
    token = request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(
        token, session.get("dvd_approval_csrf_token", "")
    ):
        abort(400)
    if request.form.get("confirm_issue") != "yes":
        abort(400)

    connection = get_db_connection()
    try:
        # Lock before checking status/counters: two clicks cannot issue twice.
        connection.execute("BEGIN IMMEDIATE")
        marker = connection.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='demo_metadata'
        """).fetchone()
        if not marker or not connection.execute("""
            SELECT 1 FROM demo_metadata WHERE marker='OMS_DEMO_V1'
        """).fetchone():
            abort(403)
        actor = connection.execute("""
            SELECT a.id AS account_id, e.id AS employee_id,
                   e.name, e.pin
            FROM user_accounts a JOIN employees e ON e.id=a.employee_id
            WHERE a.id=? AND a.is_active=1 AND e.is_active=1
        """, (session["user_account_id"],)).fetchone()
        if actor is None:
            abort(403)
        dvd = connection.execute("""
            SELECT requester_employee_id, dvd_category, status
            FROM dvd_requests WHERE id=?
        """, (request_id,)).fetchone()
        if dvd is None:
            abort(404)
        if dvd["requester_employee_id"] == actor["employee_id"]:
            abort(403)
        if dvd["status"] != "SD Approved":
            abort(409)
        if connection.execute("""
            SELECT 1 FROM dvd_discs WHERE request_id=? LIMIT 1
        """, (request_id,)).fetchone():
            abort(409)
        items = connection.execute("""
            SELECT quantity FROM dvd_request_items WHERE request_id=?
        """, (request_id,)).fetchall()
        quantity = sum(item["quantity"] for item in items)
        if not items or quantity < 1 or quantity > 20000:
            abort(409)

        # Counter format is a DEMO convention, not a final office policy.
        import json
        from datetime import datetime as _datetime
        year = _datetime.now().year
        category = dvd["dvd_category"]
        prefix = {
            "Internal": "INT", "Internet": "NET",
            "External": "EXT", "Vendor": "VEN",
            "Outward": "OUT", "Permanent": "PER",
        }.get(category)
        if prefix is None:
            abort(409)
        counter = connection.execute("""
            SELECT next_serial FROM dvd_counters
            WHERE category=? AND year=?
        """, (category, year)).fetchone()
        serial = counter["next_serial"] if counter else 1
        if serial < 1:
            abort(409)
        allocated_at = _datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for number in range(serial, serial + quantity):
            disc_no = f"{prefix}-{year}-{number:06d}"
            connection.execute("""
                INSERT INTO dvd_discs
                    (request_id, number, base_number, generation,
                     state, allocated_at, handed_at)
                VALUES (?, ?, ?, 0, 'Issued', ?, ?)
            """, (request_id, disc_no, disc_no,
                  allocated_at, allocated_at))
        if counter:
            connection.execute("""
                UPDATE dvd_counters SET next_serial=?
                WHERE category=? AND year=?
            """, (serial + quantity, category, year))
        else:
            connection.execute("""
                INSERT INTO dvd_counters(category, year, next_serial)
                VALUES (?, ?, ?)
            """, (category, year, serial + quantity))
        changed = connection.execute("""
            UPDATE dvd_requests SET status='Issued'
            WHERE id=? AND status='SD Approved'
        """, (request_id,))
        if changed.rowcount != 1:
            abort(409)
        connection.execute("""
            INSERT INTO dvd_events
                (request_id, actor_account_id, actor_snapshot, action, details)
            VALUES (?, ?, ?, 'dvd_issued', ?)
        """, (
            request_id, actor["account_id"],
            json.dumps({"pin": actor["pin"], "name": actor["name"]}),
            json.dumps({"quantity": quantity, "category": category,
                        "first_number": f"{prefix}-{year}-{serial:06d}",
                        "last_number": f"{prefix}-{year}-{serial+quantity-1:06d}"}),
        ))
        connection.commit()
    finally:
        connection.close()
    return redirect(f"/dvd-request/{request_id}")

@app.route("/dvd-requests/my")
def my_dvd_requests():

    if not (
        account_has_permission("dvd.request.view_own")
        or account_has_permission("dvd.request.view_all")
    ):
        abort(403)

    connection = get_db_connection()

    try:
        account = connection.execute("""
            SELECT employee_id
            FROM user_accounts
            WHERE id = ?
              AND is_active = 1
        """, (
            session["user_account_id"],
        )).fetchone()

        if account is None:
            abort(403)

        dvd_requests = connection.execute("""
            SELECT
                r.id,
                r.dvd_category,
                r.permanent_source_type,
                r.status,
                r.created_at,
                COUNT(i.id) AS item_count,
                COALESCE(SUM(i.quantity), 0) AS total_quantity

            FROM dvd_requests AS r

            LEFT JOIN dvd_request_items AS i
                ON i.request_id = r.id

            WHERE r.requester_employee_id = ?

            GROUP BY
                r.id,
                r.dvd_category,
                r.permanent_source_type,
                r.status,
                r.created_at

            ORDER BY r.id DESC
        """, (
            account["employee_id"],
        )).fetchall()

    finally:
        connection.close()

    return render_template(
        "my_dvd_requests.html",
        dvd_requests=dvd_requests
    )

@app.route("/dvd-request/<int:request_id>")
def dvd_request_details(request_id):
    """Owners and role-scoped pending reviewers can view request details."""
    connection = get_db_connection()
    try:
        account = connection.execute("""
            SELECT employee_id FROM user_accounts
            WHERE id = ? AND is_active = 1
        """, (session["user_account_id"],)).fetchone()
        if account is None:
            abort(403)

        employee_id = account["employee_id"]
        can_view_all = account_has_permission("dvd.request.view_all")
        can_view_own = account_has_permission("dvd.request.view_own")
        can_manage = account_has_permission("dvd.request.manager_approve")
        can_cyber = account_has_permission("dvd.request.cyber_review")
        can_it = account_has_permission("dvd.request.technical_process")

        access = connection.execute("""
            SELECT r.requester_employee_id, r.status,
                EXISTS (
                    SELECT 1 FROM employee_location_assignments AS loc
                    WHERE loc.employee_id = r.requester_employee_id
                      AND loc.is_active = 1
                      AND (
                          EXISTS (
                              SELECT 1 FROM division_management_assignments AS m
                              WHERE m.employee_id = ? AND m.is_active = 1
                                AND m.division_id = loc.organizational_unit_id
                          ) OR EXISTS (
                              SELECT 1 FROM section_head_assignments AS h
                              WHERE h.employee_id = ? AND h.is_active = 1
                                AND h.section_id = loc.section_id
                          )
                      )
                ) AS manager_responsible
            FROM dvd_requests AS r WHERE r.id = ?
        """, (employee_id, employee_id, request_id)).fetchone()
        if access is None:
            abort(404)

        is_owner = access["requester_employee_id"] == employee_id
        allowed = (
            can_view_all
            or (can_view_own and is_owner)
            or (not is_owner and (
                (can_manage and access["status"] == "Submitted"
                 and access["manager_responsible"])
                or (can_cyber and access["status"] == "Manager Approved")
                or (can_it and access["status"] in ("Cyber Approved", "SD Approved"))
            ))
        )
        if not allowed:
            abort(403)

        dvd_request = connection.execute("""
            SELECT
                dvd_requests.id, dvd_requests.dvd_category,
                dvd_requests.permanent_source_type, dvd_requests.status,
                dvd_requests.created_at, employees.pin, employees.name,
                employees.extension_number,
                designations.name AS designation_name,
                organizational_units.name AS unit_name
            FROM dvd_requests
            JOIN employees ON dvd_requests.requester_employee_id = employees.id
            JOIN designations ON employees.designation_id = designations.id
            JOIN organizational_units ON employees.organizational_unit_id = organizational_units.id
            WHERE dvd_requests.id = ?
        """, (request_id,)).fetchone()
        if dvd_request is None:
            abort(404)

        dvd_items = connection.execute("""
            SELECT id, description, quantity, remarks
            FROM dvd_request_items WHERE request_id = ? ORDER BY id ASC
        """, (request_id,)).fetchall()
    finally:
        connection.close()

    return render_template(
        "dvd_request_details.html", dvd_request=dvd_request, dvd_items=dvd_items
    )

@app.route(
    "/admin/employees/edit/<int:employee_id>",
    methods=["GET", "POST"]
)
def edit_employee(employee_id):

    connection = get_db_connection()

    employee = connection.execute("""
        SELECT
            employees.id,
            employees.pin,
            employees.name,
            employees.extension_number,
            employees.is_active,

            designation_assignment.id
                AS designation_assignment_id,

            COALESCE(
                designation_assignment.designation_id,
                employees.designation_id
            ) AS current_designation_id,

            location_assignment.id
                AS location_assignment_id,

            location_assignment.organizational_unit_id
                AS current_unit_id,

            location_assignment.section_id
                AS current_section_id

        FROM employees

        LEFT JOIN employee_designation_assignments
            AS designation_assignment

            ON designation_assignment.employee_id
               = employees.id
           AND designation_assignment.is_active = 1

        LEFT JOIN employee_location_assignments
            AS location_assignment

            ON location_assignment.employee_id
               = employees.id
           AND location_assignment.is_active = 1

        WHERE employees.id = ?
    """, (employee_id,)).fetchone()

    if employee is None:
        connection.close()
        return "Employee not found.", 404

    if request.method == "POST":

        pin = request.form.get("pin", "").strip()

        name = clean_name(
            request.form.get("name", "")
        )

        designation_id_value = request.form.get(
            "designation_id",
            ""
        ).strip()

        organizational_unit_id_value = request.form.get(
            "organizational_unit_id",
            ""
        ).strip()

        section_id_value = request.form.get(
            "section_id",
            ""
        ).strip()

        extension_number = request.form.get(
            "extension_number",
            ""
        ).strip()

        if not pin or not pin.isdigit():
            connection.close()
            return "PIN must contain digits only.", 400

        if not name:
            connection.close()
            return "Employee name is required.", 400

        # Same employee ko exclude karke duplicate PIN check karein.
        duplicate_pin = connection.execute("""
            SELECT id
            FROM employees
            WHERE pin = ?
              AND id != ?
        """, (
            pin,
            employee_id
        )).fetchone()

        if duplicate_pin:
            connection.close()

            return (
                "Another employee already has this PIN. "
                "Change that employee's PIN first.",
                400
            )

        if not designation_id_value.isdigit():
            connection.close()
            return "Please select a valid designation.", 400

        designation_id = int(designation_id_value)

        designation = connection.execute("""
            SELECT id
            FROM designations
            WHERE id = ?
              AND (
                    is_active = 1
                    OR id = ?
              )
        """, (
            designation_id,
            employee["current_designation_id"]
        )).fetchone()

        if designation is None:
            connection.close()
            return "The selected designation is not available.", 400

        organizational_unit_id = None
        section_id = None
        organizational_unit = None

        # Blank unit ka matlab employee Without Division rahega.
        if organizational_unit_id_value:

            if not organizational_unit_id_value.isdigit():
                connection.close()
                return "Please select a valid Division or Office.", 400

            organizational_unit_id = int(
                organizational_unit_id_value
            )

            organizational_unit = connection.execute("""
                SELECT
                    id,
                    name,
                    unit_type
                FROM organizational_units
                WHERE id = ?
                  AND unit_type IN (
                      'Division',
                      'Office'
                  )
                  AND is_active = 1
            """, (organizational_unit_id,)).fetchone()

            if organizational_unit is None:
                connection.close()

                return (
                    "The selected Division or Office is not active.",
                    400
                )

        if section_id_value:

            if organizational_unit_id is None:
                connection.close()

                return (
                    "A Section cannot be selected without a Division.",
                    400
                )

            if not section_id_value.isdigit():
                connection.close()
                return "Please select a valid Section.", 400

            section_id = int(section_id_value)

            section = connection.execute("""
                SELECT id
                FROM organizational_units
                WHERE id = ?
                  AND unit_type = 'Section'
                  AND parent_id = ?
                  AND is_active = 1
            """, (
                section_id,
                organizational_unit_id
            )).fetchone()

            if section is None:
                connection.close()

                return (
                    "The selected Section does not belong to the "
                    "selected Division.",
                    400
                )

        if (
            organizational_unit is not None
            and organizational_unit["unit_type"] == "Office"
            and section_id is not None
        ):
            connection.close()

            return (
                "An Office employee cannot be assigned to a Section.",
                400
            )

        try:

            # =================================================
            # DESIGNATION CHANGE
            # =================================================

            current_designation_id = (
                employee["current_designation_id"]
            )

            if (
                employee["designation_assignment_id"] is None
                or designation_id != current_designation_id
            ):

                connection.execute("""
                    UPDATE employee_designation_assignments
                    SET is_active = 0,
                        end_date = COALESCE(
                            end_date,
                            CURRENT_DATE
                        )
                    WHERE employee_id = ?
                      AND is_active = 1
                """, (employee_id,))

                connection.execute("""
                    INSERT INTO employee_designation_assignments
                    (
                        employee_id,
                        designation_id,
                        start_date,
                        is_active
                    )
                    VALUES (?, ?, CURRENT_DATE, 1)
                """, (
                    employee_id,
                    designation_id
                ))

            # =================================================
            # LOCATION OR SECTION CHANGE
            # =================================================

            current_unit_id = employee["current_unit_id"]
            current_section_id = employee["current_section_id"]

            location_changed = (
                organizational_unit_id != current_unit_id
                or section_id != current_section_id
            )

            if location_changed:


                                # Agar employee apni current Division chhor raha hai,
                # to uski tamam active Section Head responsibilities
                # automatically close ho jayengi.
                #
                # Same Division ke andar Section change karne par
                # Head responsibility close nahi hogi.
                if organizational_unit_id != current_unit_id:

                    # Head post ke saath linked Section responsibilities
                    # bhi history mein inactive karein.
                    connection.execute("""
                        UPDATE post_assignment_units
                        SET is_active = 0,
                            end_date = COALESCE(
                                end_date,
                                CURRENT_DATE
                            )
                        WHERE is_active = 1
                          AND EXISTS (
                                SELECT 1
                                FROM section_head_assignments
                                WHERE section_head_assignments.employee_id = ?
                                  AND section_head_assignments.is_active = 1
                                  AND section_head_assignments.post_assignment_id
                                      = post_assignment_units.post_assignment_id
                                  AND section_head_assignments.section_id
                                      = post_assignment_units.organizational_unit_id
                          )
                    """, (employee_id,))

                    connection.execute("""
                        UPDATE section_head_assignments
                        SET is_active = 0,
                            end_date = COALESCE(
                                end_date,
                                CURRENT_DATE
                            )
                        WHERE employee_id = ?
                          AND is_active = 1
                    """, (employee_id,))

                # Old Division/Office/Section assignment close karein.
                connection.execute("""
                    UPDATE employee_location_assignments
                    SET is_active = 0,
                        end_date = COALESCE(
                            end_date,
                            CURRENT_DATE
                        )
                    WHERE employee_id = ?
                      AND is_active = 1
                """, (employee_id,))

                # Unit selected ho to new location assignment create karein.
                if organizational_unit_id is not None:

                    connection.execute("""
                        INSERT INTO employee_location_assignments
                        (
                            employee_id,
                            organizational_unit_id,
                            section_id,
                            start_date,
                            is_active
                        )
                        VALUES (?, ?, ?, CURRENT_DATE, 1)
                    """, (
                        employee_id,
                        organizational_unit_id,
                        section_id
                    ))

            # =================================================
            # CURRENT EMPLOYEE MASTER DATA
            # =================================================

            if organizational_unit_id is not None:

                connection.execute("""
                    UPDATE employees
                    SET pin = ?,
                        name = ?,
                        designation_id = ?,
                        organizational_unit_id = ?,
                        extension_number = ?
                    WHERE id = ?
                """, (
                    pin,
                    name,
                    designation_id,
                    organizational_unit_id,
                    extension_number,
                    employee_id
                ))

            else:

                # Legacy organizational_unit_id NOT NULL hai.
                # Without Division ka real status active location
                # assignment na hone se determine hoga.
                connection.execute("""
                    UPDATE employees
                    SET pin = ?,
                        name = ?,
                        designation_id = ?,
                        extension_number = ?
                    WHERE id = ?
                """, (
                    pin,
                    name,
                    designation_id,
                    extension_number,
                    employee_id
                ))

            connection.commit()
            connection.close()

            return redirect("/admin/employees")

        except sqlite3.IntegrityError:

            connection.rollback()
            connection.close()

            return (
                "Employee could not be updated because one of the "
                "new values conflicts with an existing record.",
                400
            )

    designations = connection.execute("""
        SELECT id, name, is_active
        FROM designations
        WHERE is_active = 1
           OR id = ?
        ORDER BY name
    """, (
        employee["current_designation_id"],
    )).fetchall()

    units = connection.execute("""
        SELECT
            id,
            name,
            unit_type
        FROM organizational_units
        WHERE unit_type IN (
            'Division',
            'Office'
        )
          AND is_active = 1
        ORDER BY
            CASE unit_type
                WHEN 'Division' THEN 1
                WHEN 'Office' THEN 2
            END,
            name
    """).fetchall()

    sections = connection.execute("""
        SELECT
            section.id,
            section.name,
            section.parent_id
        FROM organizational_units AS section

        JOIN organizational_units AS parent_division
            ON section.parent_id = parent_division.id

        WHERE section.unit_type = 'Section'
          AND section.is_active = 1
          AND parent_division.unit_type = 'Division'
          AND parent_division.is_active = 1

        ORDER BY section.name
    """).fetchall()

    connection.close()

    return render_template(
        "edit_employee.html",
        employee=employee,
        designations=designations,
        units=units,
        sections=sections
    )

# =================================================
# POSTS / CHARGES
# =================================================

@app.route("/admin/posts")
def manage_posts():

    connection = get_db_connection()

    assignments = connection.execute("""
        SELECT
            employee_post_assignments.id,

            employees.pin,

            employees.name AS employee_name,

            posts.name AS post_name,

            GROUP_CONCAT(
                DISTINCT organizational_units.name
            ) AS unit_name,

            employee_post_assignments.start_date,

            employee_post_assignments.end_date,

            employee_post_assignments.is_active

        FROM employee_post_assignments

        JOIN employees
            ON employee_post_assignments.employee_id
               = employees.id

        JOIN posts
            ON employee_post_assignments.post_id
               = posts.id

        LEFT JOIN post_assignment_units
            ON post_assignment_units.post_assignment_id
               = employee_post_assignments.id

        LEFT JOIN organizational_units
            ON post_assignment_units.organizational_unit_id
               = organizational_units.id

        GROUP BY employee_post_assignments.id

        ORDER BY
            employee_post_assignments.is_active DESC,
            posts.name,
            employees.name
    """).fetchall()

    connection.close()

    return render_template(
        "posts.html",
        assignments=assignments
    )



@app.route("/admin/posts/assign", methods=["GET", "POST"])
def assign_post():

    connection = get_db_connection()

    if request.method == "POST":

        employee_id = request.form["employee_id"]
        post_id = request.form["post_id"]

        organizational_unit_ids = request.form.getlist(
            "organizational_unit_ids"
        )

        # Duplicate unit IDs remove kar dein.
        organizational_unit_ids = list(
            dict.fromkeys(organizational_unit_ids)
        )

        # -----------------------------------------
        # Employee validation
        # -----------------------------------------

        employee = connection.execute("""
            SELECT
                id,
                pin,
                name
            FROM employees
            WHERE id = ?
              AND is_active = 1
        """, (employee_id,)).fetchone()

        if employee is None:

            connection.close()

            return """
                <h2>Employee not found</h2>

                <p>
                    Selected employee does not exist
                    or is currently inactive.
                </p>

                <a href="/admin/posts/assign">
                    Go Back
                </a>
            """, 404

        # -----------------------------------------
        # Post validation
        # -----------------------------------------

        post = connection.execute("""
            SELECT
                id,
                name,
                max_active_holders
            FROM posts
            WHERE id = ?
              AND is_active = 1
        """, (post_id,)).fetchone()

        if post is None:

            connection.close()

            return """
                <h2>Post not found</h2>

                <p>
                    Selected post does not exist
                    or is currently inactive.
                </p>

                <a href="/admin/posts/assign">
                    Go Back
                </a>
            """, 404

        # -----------------------------------------
        # One employee = one active post
        # -----------------------------------------

        employee_active_post = connection.execute("""
            SELECT
                posts.name AS post_name
            FROM employee_post_assignments

            JOIN posts
                ON employee_post_assignments.post_id
                   = posts.id

            WHERE employee_post_assignments.employee_id = ?
              AND employee_post_assignments.is_active = 1
        """, (employee_id,)).fetchone()

        if employee_active_post:

            connection.close()

            return f"""
                <h2>Employee already has an active post</h2>

                <p>
                    <strong>{employee["name"]}</strong>
                    currently holds the post:
                    <strong>
                        {employee_active_post["post_name"]}
                    </strong>
                </p>

                <p>
                    End the current assignment before
                    assigning another post.
                </p>

                <a href="/admin/posts">
                    Go Back
                </a>
            """, 400

        # -----------------------------------------
        # Unit requirement
        # -----------------------------------------

        unit_based_posts = (
            "Manager",
            "Acting Manager",
            "Head"
        )

        if (
            post["name"] in unit_based_posts
            and not organizational_unit_ids
        ):

            connection.close()

            return """
                <h2>Responsible unit is required</h2>

                <p>
                    Manager, Acting Manager and Head
                    must have at least one responsible
                    division or unit.
                </p>

                <a href="/admin/posts/assign">
                    Go Back
                </a>
            """, 400

        # -----------------------------------------
        # Selected units validation
        # -----------------------------------------

        if organizational_unit_ids:

            placeholders = ",".join(
                "?" for unit_id in organizational_unit_ids
            )

            valid_unit_count = connection.execute(f"""
                SELECT COUNT(*)
                FROM organizational_units

                WHERE id IN ({placeholders})
                  AND is_active = 1
                  AND unit_type != 'Authority'
            """, organizational_unit_ids).fetchone()[0]

            if valid_unit_count != len(
                organizational_unit_ids
            ):

                connection.close()

                return """
                    <h2>Invalid organizational unit</h2>

                    <p>
                        One or more selected units
                        are invalid or inactive.
                    </p>

                    <a href="/admin/posts/assign">
                        Go Back
                    </a>
                """, 400

        required_unit_type = {"Head": "Section", "Manager": "Division", "Acting Manager": "Division"}.get(post["name"])
        if required_unit_type:
            placeholders = ",".join("?" for _ in organizational_unit_ids)
            matching = connection.execute(
                f"SELECT COUNT(*) FROM organizational_units WHERE id IN ({placeholders}) AND unit_type=? AND is_active=1",
                [*organizational_unit_ids, required_unit_type]
            ).fetchone()[0]
            if matching != len(organizational_unit_ids):
                connection.close()
                return f"{post['name']} responsibility requires active {required_unit_type} units.", 400

        # -----------------------------------------
        # Unique post holder validation
        # -----------------------------------------

        if post["max_active_holders"] == 1:

            existing_holder = connection.execute("""
                SELECT
                    employees.pin,
                    employees.name
                FROM employee_post_assignments

                JOIN employees
                    ON employee_post_assignments.employee_id
                       = employees.id

                WHERE employee_post_assignments.post_id = ?
                  AND employee_post_assignments.is_active = 1
            """, (post_id,)).fetchone()

            if existing_holder:

                connection.close()

                return f"""
                    <h2>Post already assigned</h2>

                    <p>
                        <strong>{post["name"]}</strong>
                        is already assigned to:
                    </p>

                    <p>
                        PIN:
                        <strong>
                            {existing_holder["pin"]}
                        </strong>

                        <br>

                        Employee:
                        <strong>
                            {existing_holder["name"]}
                        </strong>
                    </p>

                    <p>
                        Only one active holder is allowed
                        for this post.
                    </p>

                    <a href="/admin/posts">
                        Go Back
                    </a>
                """, 400

        # -----------------------------------------
        # Save post assignment
        # -----------------------------------------

        try:

            cursor = connection.execute("""
                INSERT INTO employee_post_assignments
                (
                    employee_id,
                    post_id,
                    organizational_unit_id
                )
                VALUES (?, ?, NULL)
            """, (
                employee_id,
                post_id
            ))

            post_assignment_id = cursor.lastrowid

            # Multiple responsible units ko
            # single post assignment ke saath link karein.
            for organizational_unit_id in organizational_unit_ids:

                connection.execute("""
                    INSERT INTO post_assignment_units
                    (
                        post_assignment_id,
                        organizational_unit_id
                    )
                    VALUES (?, ?)
                """, (
                    post_assignment_id,
                    organizational_unit_id
                ))

            connection.commit()
            connection.close()

            return redirect("/admin/posts")

        except sqlite3.IntegrityError:

            connection.rollback()
            connection.close()

            return """
                <h2>Assignment could not be saved</h2>

                <p>
                    This assignment conflicts with
                    an existing active post or unit.
                </p>

                <a href="/admin/posts">
                    Go Back
                </a>
            """, 400

    # ---------------------------------------------
    # GET request: dropdown data
    # ---------------------------------------------

    employees = connection.execute("""
        SELECT
            employees.id,
            employees.pin,
            employees.name,

            designations.name AS designation_name

        FROM employees

        JOIN designations
            ON employees.designation_id
               = designations.id

        WHERE employees.is_active = 1

        ORDER BY employees.name
    """).fetchall()

    posts = connection.execute("""
        SELECT
            id,
            name,
            max_active_holders
        FROM posts

        WHERE is_active = 1

        ORDER BY
            CASE name
                WHEN 'Senior Director' THEN 1
                WHEN 'Plant Manager' THEN 2
                WHEN 'Deputy Plant Manager' THEN 3
                WHEN 'Manager' THEN 4
                WHEN 'Acting Manager' THEN 5
                WHEN 'Head' THEN 6
                WHEN 'HLAO' THEN 7
                WHEN 'Principal Administrator' THEN 8
                ELSE 9
            END,
            name
    """).fetchall()

    units = connection.execute("""
        SELECT
            id,
            name,
            unit_type
        FROM organizational_units

        WHERE is_active = 1
          AND unit_type != 'Authority'

        ORDER BY name
    """).fetchall()

    connection.close()

    return render_template(
        "assign_post.html",
        employees=employees,
        posts=posts,
        units=units
    )


# =================================================
# END POST / CHARGE ASSIGNMENT
# =================================================

@app.route(
    "/admin/posts/end/<int:assignment_id>",
    methods=["POST"]
)
def end_post_assignment(assignment_id):

    connection = get_db_connection()

    assignment = connection.execute("""
        SELECT id
        FROM employee_post_assignments

        WHERE id = ?
          AND is_active = 1
    """, (assignment_id,)).fetchone()

    if assignment is None:

        connection.close()

        return """
            <h2>Active assignment not found</h2>

            <p>
                This assignment has already ended
                or does not exist.
            </p>

            <a href="/admin/posts">
                Go Back
            </a>
        """, 404
         # Post end hone se pehle us post ke saath linked
    # Section Head responsibilities close karein.
    connection.execute("""
        UPDATE section_head_assignments
        SET is_active = 0,
            end_date = COALESCE(
                end_date,
                CURRENT_DATE
            )
        WHERE post_assignment_id = ?
          AND is_active = 1
    """, (assignment_id,))

    # Manager ya Acting Manager ki linked Division
    # responsibilities bhi history mein close karein.
    connection.execute("""
        UPDATE division_management_assignments
        SET is_active = 0,
            end_date = COALESCE(
                end_date,
                CURRENT_DATE
            )
        WHERE post_assignment_id = ?
          AND is_active = 1
    """, (assignment_id,))
    
    # Responsible units ko inactive karein.
    # Records delete nahi honge.
    connection.execute("""
        UPDATE post_assignment_units

        SET is_active = 0,
            end_date = COALESCE(
                end_date,
                CURRENT_DATE
            )

        WHERE post_assignment_id = ?
          AND is_active = 1
    """, (assignment_id,))

    # Main post assignment end karein.
    connection.execute("""
        UPDATE employee_post_assignments

        SET is_active = 0,
            end_date = COALESCE(
                end_date,
                CURRENT_DATE
            )

        WHERE id = ?
    """, (assignment_id,))

    connection.commit()
    connection.close()

    return redirect("/admin/posts")

# =================================================
# ADMIN - USER ACCOUNTS (STEP 1)
# =================================================
@app.route("/admin/accounts", methods=["GET", "POST"])
def manage_user_accounts():
    if not account_has_permission("accounts.manage"):
        abort(403)

    token = session.setdefault("account_admin_csrf_token", secrets.token_urlsafe(32))
    error = None
    success = None

    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        if not submitted or not secrets.compare_digest(submitted, token):
            abort(400)
        pin = request.form.get("pin", "").strip()
        password = request.form.get("temporary_password", "")
        if not pin.isdigit():
            error = "Enter a valid numeric employee PIN."
        elif len(password) < 12:
            error = "Temporary password must have at least 12 characters."
        else:
            with closing(get_db_connection()) as conn:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    emp = conn.execute("""
                        SELECT e.id, e.name, e.is_active, u.id AS account_id
                        FROM employees e LEFT JOIN user_accounts u ON u.employee_id=e.id
                        WHERE e.pin=?
                    """, (pin,)).fetchone()
                    role = conn.execute("""
                        SELECT id FROM system_roles
                        WHERE name='Employee' AND is_active=1
                    """).fetchone()
                    if emp is None or emp["is_active"] != 1:
                        error = "Active employee not found."
                    elif emp["account_id"] is not None:
                        error = "This employee already has a login account."
                    elif role is None:
                        error = "Employee system role not available."
                    else:
                        cursor = conn.execute("""
                            INSERT INTO user_accounts
                              (employee_id, password_hash, must_change_password)
                            VALUES (?, ?, 1)
                        """, (emp["id"], generate_password_hash(password)))
                        conn.execute("""
                            INSERT INTO user_role_assignments
                              (user_account_id, system_role_id, assigned_by_user_account_id)
                            VALUES (?, ?, ?)
                        """, (cursor.lastrowid, role["id"], session["user_account_id"]))
                        conn.commit()
                        return redirect("/admin/accounts?created=1")
                    conn.rollback()
                except sqlite3.IntegrityError:
                    conn.rollback()
                    error = "Account creation failed due to an existing record."

    with closing(get_db_connection()) as conn:
        rows = conn.execute("""
            SELECT e.pin, e.name, e.is_active AS employee_active,
                   u.id AS account_id, u.is_active AS account_active,
                   u.must_change_password,
                   GROUP_CONCAT(CASE WHEN a.is_active=1 THEN r.name END, ', ') AS roles
            FROM employees e
            LEFT JOIN user_accounts u ON u.employee_id=e.id
            LEFT JOIN user_role_assignments a ON a.user_account_id=u.id
            LEFT JOIN system_roles r ON r.id=a.system_role_id
            GROUP BY e.id, u.id
            ORDER BY e.name
        """).fetchall()
    return render_template("user_accounts.html", accounts=rows,
                           csrf_token=token, error=error,
                           created=request.args.get("created") == "1")



# =================================================
# ADMIN - ACCOUNT ROLE ASSIGNMENT (STEP 2)
# =================================================
@app.route("/admin/accounts/<int:account_id>/roles", methods=["GET", "POST"])
def manage_account_roles(account_id):
    # Role management is restricted to an active Super Admin user,
    # not merely anybody with roles.manage (Admin also has that permission).
    if not account_has_permission("roles.manage"):
        abort(403)
    with closing(get_db_connection()) as conn:
        is_super = conn.execute("""
            SELECT 1 FROM user_role_assignments a
            JOIN system_roles r ON r.id=a.system_role_id AND r.is_active=1
            WHERE a.user_account_id=? AND a.is_active=1 AND r.name='Super Admin'
        """, (session["user_account_id"],)).fetchone()
    if not is_super:
        abort(403)

    allowed_names = ("Employee", "Manager", "Cyber Security", "Technical Incharge")
    token = session.setdefault("role_admin_csrf_token", secrets.token_urlsafe(32))
    error = None

    with closing(get_db_connection()) as conn:
        account = conn.execute("""
            SELECT u.id, u.is_active AS account_active, e.pin, e.name,
                   e.is_active AS employee_active
            FROM user_accounts u JOIN employees e ON e.id=u.employee_id
            WHERE u.id=?
        """, (account_id,)).fetchone()
    if account is None:
        abort(404)
    if account_id == session["user_account_id"]:
        abort(403)  # no self-grants, including edits to own role history

    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        if not submitted or not secrets.compare_digest(submitted, token):
            abort(400)
        role_name = request.form.get("role_name", "")
        operation = request.form.get("operation", "")
        if role_name not in allowed_names or operation not in ("grant", "revoke"):
            abort(400)
        if not account["account_active"] or not account["employee_active"]:
            error = "Inactive accounts cannot have roles changed."
        else:
            with closing(get_db_connection()) as conn:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    role = conn.execute("""
                        SELECT id FROM system_roles WHERE name=? AND is_active=1
                    """, (role_name,)).fetchone()
                    if role is None:
                        error = "Role not available in this database."
                    else:
                        current = conn.execute("""
                            SELECT id FROM user_role_assignments
                            WHERE user_account_id=? AND system_role_id=? AND is_active=1
                        """, (account_id, role["id"])).fetchone()
                        if operation == "grant" and current is None:
                            conn.execute("""
                                INSERT INTO user_role_assignments
                                  (user_account_id, system_role_id, assigned_by_user_account_id)
                                VALUES (?, ?, ?)
                            """, (account_id, role["id"], session["user_account_id"]))
                        elif operation == "revoke" and current is not None:
                            if role_name == "Employee":
                                error = "Employee baseline role cannot be revoked here."
                            else:
                                conn.execute("""
                                    UPDATE user_role_assignments
                                    SET is_active=0, end_date=CURRENT_TIMESTAMP
                                    WHERE id=? AND is_active=1
                                """, (current["id"],))
                    if error:
                        conn.rollback()
                    else:
                        conn.commit()
                        return redirect(f"/admin/accounts/{account_id}/roles?updated=1")
                except sqlite3.IntegrityError:
                    conn.rollback()
                    error = "Role update could not be saved."

    with closing(get_db_connection()) as conn:
        roles = conn.execute("""
            SELECT r.name, a.is_active, a.start_date, a.end_date,
                   a.assigned_by_user_account_id
            FROM user_role_assignments a JOIN system_roles r ON r.id=a.system_role_id
            WHERE a.user_account_id=? ORDER BY a.id DESC
        """, (account_id,)).fetchall()
    active = {r["name"] for r in roles if r["is_active"]}
    return render_template("account_roles.html", account=account, roles=roles,
                           active=active, allowed_names=allowed_names,
                           csrf_token=token, error=error,
                           updated=request.args.get("updated") == "1")


# =================================================
# ADMIN - ENABLE / DISABLE EMPLOYEE LOGIN (STEP 3)
# =================================================
@app.route("/admin/accounts/<int:account_id>/status", methods=["POST"])
def set_login_account_status(account_id):
    if not account_has_permission("accounts.manage"):
        abort(403)
    # Sensitive account changes require an active Super Admin role.
    with closing(get_db_connection()) as conn:
        actor = conn.execute("""
            SELECT 1 FROM user_role_assignments a
            JOIN system_roles r ON r.id=a.system_role_id AND r.is_active=1
            WHERE a.user_account_id=? AND a.is_active=1
              AND r.name='Super Admin'
        """, (session["user_account_id"],)).fetchone()
    if actor is None or account_id == session["user_account_id"]:
        abort(403)

    provided = request.form.get("csrf_token", "")
    expected = session.get("account_admin_csrf_token", "")
    if not provided or not expected or not secrets.compare_digest(provided, expected):
        abort(400)
    action = request.form.get("action", "")
    if action not in ("disable", "enable"):
        abort(400)

    with closing(get_db_connection()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            account = conn.execute("""
                SELECT u.is_active AS login_active, e.is_active AS employee_active
                FROM user_accounts u JOIN employees e ON e.id=u.employee_id
                WHERE u.id=?
            """, (account_id,)).fetchone()
            if account is None:
                abort(404)
            # Never change access for an account holding Super Admin privileges.
            privileged = conn.execute("""
                SELECT 1 FROM user_role_assignments a
                JOIN system_roles r ON r.id=a.system_role_id
                WHERE a.user_account_id=? AND a.is_active=1
                  AND r.name='Super Admin'
            """, (account_id,)).fetchone()
            if privileged:
                abort(403)
            if action == "enable" and not account["employee_active"]:
                abort(409)
            new_value = 1 if action == "enable" else 0
            conn.execute("""
                UPDATE user_accounts SET is_active=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (new_value, account_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return redirect("/admin/accounts?status_updated=1")
