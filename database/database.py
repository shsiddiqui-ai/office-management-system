import sqlite3


connection = sqlite3.connect("database/office.db")

connection.execute("PRAGMA foreign_keys = ON")


# =================================================
# ORGANIZATIONAL UNITS
# =================================================

connection.execute("""
CREATE TABLE IF NOT EXISTS organizational_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL,

    unit_type TEXT NOT NULL
        CHECK (
            unit_type IN (
                'Authority',
                'Division',
                'Office',
                'Department',
                'Section'
            )
        ),

    parent_id INTEGER,

    is_active INTEGER NOT NULL DEFAULT 1,

    FOREIGN KEY (parent_id)
        REFERENCES organizational_units(id)
)
""")


# =================================================
# DESIGNATIONS
# =================================================

connection.execute("""
CREATE TABLE IF NOT EXISTS designations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL COLLATE NOCASE UNIQUE,

    is_active INTEGER NOT NULL DEFAULT 1
)
""")


# =================================================
# EMPLOYEES
# =================================================

connection.execute("""
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    pin TEXT NOT NULL UNIQUE,

    name TEXT NOT NULL,

    designation_id INTEGER NOT NULL,

    organizational_unit_id INTEGER NOT NULL,

    extension_number TEXT,

    is_active INTEGER NOT NULL DEFAULT 1,

    FOREIGN KEY (designation_id)
        REFERENCES designations(id),

    FOREIGN KEY (organizational_unit_id)
        REFERENCES organizational_units(id)
)
""")


# =================================================
# POSTS / CHARGES
# =================================================

connection.execute("""
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL COLLATE NOCASE UNIQUE,

    max_active_holders INTEGER,

    is_active INTEGER NOT NULL DEFAULT 1
)
""")


# =================================================
# EMPLOYEE POST / CHARGE ASSIGNMENTS
# =================================================

connection.execute("""
CREATE TABLE IF NOT EXISTS employee_post_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    employee_id INTEGER NOT NULL,

    post_id INTEGER NOT NULL,

    organizational_unit_id INTEGER,

    reports_to_assignment_id INTEGER,

    start_date TEXT NOT NULL DEFAULT CURRENT_DATE,

    end_date TEXT,

    is_active INTEGER NOT NULL DEFAULT 1,

    FOREIGN KEY (employee_id)
        REFERENCES employees(id),

    FOREIGN KEY (post_id)
        REFERENCES posts(id),

    FOREIGN KEY (organizational_unit_id)
        REFERENCES organizational_units(id),

    FOREIGN KEY (reports_to_assignment_id)
        REFERENCES employee_post_assignments(id)
)
""")


# =================================================
# DVD REQUESTS
# =================================================

# =================================================
# POST / CHARGE RESPONSIBLE UNITS
# =================================================

# Ek employee ko post sirf ek baar assign hoga.
# Usi single assignment ke saath multiple units link ho sakte hain.
connection.execute("""
CREATE TABLE IF NOT EXISTS post_assignment_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    post_assignment_id INTEGER NOT NULL,

    organizational_unit_id INTEGER NOT NULL,

    start_date TEXT NOT NULL DEFAULT CURRENT_DATE,

    end_date TEXT,

    is_active INTEGER NOT NULL DEFAULT 1,

    FOREIGN KEY (post_assignment_id)
        REFERENCES employee_post_assignments(id),

    FOREIGN KEY (organizational_unit_id)
        REFERENCES organizational_units(id)
)
""")


# Ek hi post assignment ke andar same unit duplicate nahi ho sakta.
connection.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS
    idx_unique_post_assignment_unit
ON post_assignment_units (
    post_assignment_id,
    organizational_unit_id
)
""")


# Purane structure mein unit employee_post_assignments table mein thi.
# Purane unit records ko new mapping table mein transfer karein.
connection.execute("""
INSERT OR IGNORE INTO post_assignment_units
(
    post_assignment_id,
    organizational_unit_id,
    start_date,
    end_date,
    is_active
)
SELECT
    id,
    organizational_unit_id,
    start_date,
    end_date,
    is_active
FROM employee_post_assignments
WHERE organizational_unit_id IS NOT NULL
""")


# Purane test data mein ek employee ke multiple active posts ho sakte hain.
# Sabse naya assignment active rahega.
# Baqi assignments delete nahi honge, history ke liye inactive ho jayenge.
duplicate_employees = connection.execute("""
    SELECT employee_id
    FROM employee_post_assignments
    WHERE is_active = 1
    GROUP BY employee_id
    HAVING COUNT(*) > 1
""").fetchall()


for duplicate_employee in duplicate_employees:

    employee_id = duplicate_employee[0]

    active_assignments = connection.execute("""
        SELECT
            id,
            post_id
        FROM employee_post_assignments
        WHERE employee_id = ?
          AND is_active = 1
        ORDER BY id DESC
    """, (employee_id,)).fetchall()

    retained_assignment_id = active_assignments[0][0]
    retained_post_id = active_assignments[0][1]

    for old_assignment_id, old_post_id in active_assignments[1:]:

        # Agar purana aur latest post same hai to purane assignment ki
        # responsible units latest assignment ke saath merge kar dein.
        if old_post_id == retained_post_id:

            connection.execute("""
                INSERT OR IGNORE INTO post_assignment_units
                (
                    post_assignment_id,
                    organizational_unit_id,
                    start_date,
                    end_date,
                    is_active
                )
                SELECT
                    ?,
                    organizational_unit_id,
                    start_date,
                    NULL,
                    1
                FROM post_assignment_units
                WHERE post_assignment_id = ?
            """, (
                retained_assignment_id,
                old_assignment_id
            ))

        # Purani unit responsibility history mein preserve hogi.
        connection.execute("""
            UPDATE post_assignment_units
            SET is_active = 0,
                end_date = COALESCE(
                    end_date,
                    CURRENT_DATE
                )
            WHERE post_assignment_id = ?
        """, (old_assignment_id,))

        # Purana post assignment bhi delete nahi hoga.
        connection.execute("""
            UPDATE employee_post_assignments
            SET is_active = 0,
                end_date = COALESCE(
                    end_date,
                    CURRENT_DATE
                )
            WHERE id = ?
        """, (old_assignment_id,))


# Database-level rule:
# Ek employee/PIN ka sirf ONE active post/charge ho sakta hai.
connection.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS
    idx_one_active_post_per_employee
ON employee_post_assignments (employee_id)
WHERE is_active = 1
""")


connection.execute("""
CREATE TABLE IF NOT EXISTS dvd_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    requester_employee_id INTEGER NOT NULL,

    dvd_category TEXT NOT NULL
        CHECK (
            dvd_category IN (
                'Internal',
                'Internet',
                'External',
                'Vendor',
                'Outward',
                'Permanent'
            )
        ),

    permanent_source_type TEXT
        CHECK (
            permanent_source_type IS NULL
            OR permanent_source_type IN (
                'Internal',
                'Internet',
                'External',
                'Vendor'
            )
        ),

    status TEXT NOT NULL DEFAULT 'Submitted',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (requester_employee_id)
        REFERENCES employees(id)
)
""")


# =================================================
# DVD REQUEST ITEMS
# =================================================

connection.execute("""
CREATE TABLE IF NOT EXISTS dvd_request_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    request_id INTEGER NOT NULL,

    description TEXT NOT NULL,

    quantity INTEGER NOT NULL DEFAULT 1
        CHECK (quantity > 0),

    remarks TEXT,

    FOREIGN KEY (request_id)
        REFERENCES dvd_requests(id)
        ON DELETE CASCADE
)
""")


# =================================================
# DEFAULT POSTS / CHARGES
# =================================================

default_posts = [

    # Sirf ONE active holder allowed
    ("Senior Director", 1),
    ("Plant Manager", 1),
    ("Deputy Plant Manager", 1),
    ("HLAO", 1),
    ("Principal Administrator", 1),

    # Organization mein multiple holders allowed
    ("Manager", None),
    ("Acting Manager", None),
    ("Head", None)
]


for post_name, max_holders in default_posts:

    connection.execute("""
        INSERT OR IGNORE INTO posts
        (
            name,
            max_active_holders
        )
        VALUES (?, ?)
    """, (
        post_name,
        max_holders
    ))


# Account Officer aur Admin Officer designations hain,
# posts/charges nahi hain.
legacy_post_names = (
    "Account Officer",
    "Admin Officer"
)


for legacy_post_name in legacy_post_names:

    legacy_post = connection.execute("""
        SELECT id
        FROM posts
        WHERE name = ? COLLATE NOCASE
    """, (legacy_post_name,)).fetchone()

    if legacy_post:

        legacy_post_id = legacy_post[0]

        assignment_count = connection.execute("""
            SELECT COUNT(*)
            FROM employee_post_assignments
            WHERE post_id = ?
        """, (legacy_post_id,)).fetchone()[0]

        if assignment_count == 0:

            connection.execute("""
                DELETE FROM posts
                WHERE id = ?
            """, (legacy_post_id,))

        else:

            # Assignment delete nahi hogi; history preserve rahegi.
            connection.execute("""
                UPDATE employee_post_assignments
                SET is_active = 0,
                    end_date = COALESCE(
                        end_date,
                        CURRENT_DATE
                    )
                WHERE post_id = ?
                  AND is_active = 1
            """, (legacy_post_id,))

            connection.execute("""
                UPDATE posts
                SET is_active = 0
                WHERE id = ?
            """, (legacy_post_id,))
connection.commit()            
connection.close()


print("Clean Office Management System database created successfully!")