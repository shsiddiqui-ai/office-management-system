
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "database" / "office_demo.db"

if not DB.is_file():
    raise SystemExit("ERROR: Demo database not found.")

connection = sqlite3.connect(DB)
connection.row_factory = sqlite3.Row

try:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("BEGIN IMMEDIATE")

    employee = connection.execute("""
        SELECT u.id AS account_id
        FROM employees e
        JOIN user_accounts u ON u.employee_id = e.id
        WHERE e.pin = '9900016'
          AND e.name = 'DEMO Account Manager'
          AND e.is_active = 1
          AND u.is_active = 1
    """).fetchone()

    if employee is None:
        raise ValueError("Demo Manager account not found.")

    connection.execute("""
        INSERT OR IGNORE INTO system_roles
        (name, description)
        VALUES (?, ?)
    """, (
        "Manager",
        "Approves CD/DVD requests for assigned divisions and sections."
    ))

    role = connection.execute("""
        SELECT id FROM system_roles
        WHERE name = 'Manager' AND is_active = 1
    """).fetchone()

    if role is None:
        raise ValueError("Active Manager role not found.")

    permissions = [
        "dashboard.view",
        "organization.view",
        "dvd.request.create",
        "dvd.request.view_own",
        "dvd.request.manager_approve"
    ]

    for code in permissions:
        permission = connection.execute("""
            SELECT id FROM permissions
            WHERE code = ? AND is_active = 1
        """, (code,)).fetchone()

        if permission is None:
            raise ValueError(f"Missing permission: {code}")

        connection.execute("""
            INSERT OR IGNORE INTO system_role_permissions
            (system_role_id, permission_id)
            VALUES (?, ?)
        """, (role["id"], permission["id"]))

    existing = connection.execute("""
        SELECT id FROM user_role_assignments
        WHERE user_account_id = ?
          AND system_role_id = ?
          AND is_active = 1
    """, (employee["account_id"], role["id"])).fetchone()

    if existing is None:
        connection.execute("""
            INSERT INTO user_role_assignments
            (user_account_id, system_role_id,
             assigned_by_user_account_id)
            VALUES (?, ?, NULL)
        """, (employee["account_id"], role["id"]))

    violations = connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()

    if violations:
        raise ValueError("Foreign key check failed.")

    connection.commit()
    print("SUCCESS: Demo Manager role and permissions assigned.")

except Exception:
    connection.rollback()
    raise

finally:
    connection.close()
