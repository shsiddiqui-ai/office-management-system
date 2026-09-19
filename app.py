from flask import Flask, render_template, request, redirect
import sqlite3

app = Flask(__name__)


def get_db_connection():
    connection = sqlite3.connect("database/office.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def clean_name(value):
    return " ".join(value.strip().split())

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/cd-dvd")
def cd_dvd():
    return render_template("cd_dvd.html")


@app.route("/admin")
def admin_dashboard():
    return render_template("admin.html")


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

    connection.close()

    return render_template(
        "edit_unit.html",
        unit=unit,
        parent_units=parent_units
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

@app.route("/dvd-request/new", methods=["GET", "POST"])
def new_dvd_request():

    connection = get_db_connection()

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
        JOIN organizational_units
            ON employees.organizational_unit_id = organizational_units.id
        WHERE employees.is_active = 1
        ORDER BY employees.name
    """).fetchall()

    if request.method == "POST":

        requester_employee_id = request.form["requester_employee_id"]
        dvd_category = request.form["dvd_category"]
        permanent_source_type = request.form.get("permanent_source_type")

        if dvd_category == "Permanent":
            if not permanent_source_type:
                connection.close()
                return "Permanent source type is required.", 400
        else:
            permanent_source_type = None

        cursor = connection.execute("""
            INSERT INTO dvd_requests
            (
                requester_employee_id,
                dvd_category,
                permanent_source_type
            )
            VALUES (?, ?, ?)
        """, (
            requester_employee_id,
            dvd_category,
            permanent_source_type
        ))

        request_id = cursor.lastrowid

        connection.commit()
        connection.close()

        return redirect(f"/dvd-request/{request_id}")

    connection.close()

    return render_template(
        "new_dvd_request.html",
        employees=employees
    )


@app.route("/dvd-request/<int:request_id>")
def dvd_request_details(request_id):

    connection = get_db_connection()

    dvd_request = connection.execute("""
        SELECT
            dvd_requests.id,
            dvd_requests.dvd_category,
            dvd_requests.permanent_source_type,
            dvd_requests.status,
            dvd_requests.created_at,
            employees.pin,
            employees.name,
            employees.extension_number,
            designations.name AS designation_name,
            organizational_units.name AS unit_name
        FROM dvd_requests
        JOIN employees
            ON dvd_requests.requester_employee_id = employees.id
        JOIN designations
            ON employees.designation_id = designations.id
        JOIN organizational_units
            ON employees.organizational_unit_id = organizational_units.id
        WHERE dvd_requests.id = ?
    """, (request_id,)).fetchone()

    connection.close()

    if dvd_request is None:
        return "DVD request not found", 404

    return render_template(
        "dvd_request_details.html",
        dvd_request=dvd_request
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