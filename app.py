from flask import Flask, render_template, request, redirect
import sqlite3

app = Flask(__name__)


def get_db_connection():
    connection = sqlite3.connect("database/office.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


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
            organizational_units.id,
            organizational_units.name,
            organizational_units.unit_type,
            organizational_units.is_active,
            parent.name AS parent_name
        FROM organizational_units
        LEFT JOIN organizational_units AS parent
            ON organizational_units.parent_id = parent.id
        ORDER BY organizational_units.id DESC
    """).fetchall()

    connection.close()

    return render_template("units.html", units=units)


@app.route("/admin/units/add", methods=["GET", "POST"])
def add_unit():

    connection = get_db_connection()

    if request.method == "POST":

        name = request.form["name"]
        unit_type = request.form["unit_type"]
        parent_id = request.form.get("parent_id")

        if parent_id == "":
            parent_id = None

        connection.execute("""
            INSERT INTO organizational_units
            (name, unit_type, parent_id)
            VALUES (?, ?, ?)
        """, (name, unit_type, parent_id))

        connection.commit()
        connection.close()

        return redirect("/admin/units")

    parent_units = connection.execute("""
        SELECT id, name
        FROM organizational_units
        WHERE is_active = 1
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
        SELECT *
        FROM organizational_units
        WHERE id = ?
    """, (unit_id,)).fetchone()

    if unit is None:
        connection.close()
        return "Organizational unit not found", 404

    if request.method == "POST":

        name = request.form["name"]
        unit_type = request.form["unit_type"]
        parent_id = request.form.get("parent_id")

        if parent_id == "":
            parent_id = None
        else:
            parent_id = int(parent_id)

        connection.execute("""
            UPDATE organizational_units
            SET name = ?,
                unit_type = ?,
                parent_id = ?
            WHERE id = ?
        """, (name, unit_type, parent_id, unit_id))

        connection.commit()
        connection.close()

        return redirect("/admin/units")

    parent_units = connection.execute("""
        SELECT id, name
        FROM organizational_units
        WHERE is_active = 1
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

    search = request.args.get("search", "").strip()

    connection = get_db_connection()

    if search:

        search_value = f"%{search}%"

        employees = connection.execute("""
            SELECT
                employees.id,
                employees.pin,
                employees.name,
                employees.extension_number,
                employees.is_active,
                designations.name AS designation_name,
                organizational_units.name AS unit_name
            FROM employees
            JOIN designations
                ON employees.designation_id = designations.id
            JOIN organizational_units
                ON employees.organizational_unit_id = organizational_units.id
            WHERE employees.name LIKE ?
               OR employees.pin LIKE ?
               OR designations.name LIKE ?
               OR organizational_units.name LIKE ?
               OR employees.extension_number LIKE ?
            ORDER BY employees.name
        """, (
            search_value,
            search_value,
            search_value,
            search_value,
            search_value
        )).fetchall()

    else:

        employees = connection.execute("""
            SELECT
                employees.id,
                employees.pin,
                employees.name,
                employees.extension_number,
                employees.is_active,
                designations.name AS designation_name,
                organizational_units.name AS unit_name
            FROM employees
            JOIN designations
                ON employees.designation_id = designations.id
            JOIN organizational_units
                ON employees.organizational_unit_id = organizational_units.id
            ORDER BY employees.name
        """).fetchall()

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

        pin = request.form["pin"].strip()
        name = request.form["name"].strip()
        designation_id = request.form["designation_id"]
        organizational_unit_id = request.form["organizational_unit_id"]
        extension_number = request.form.get("extension_number", "").strip()

        try:

            connection.execute("""
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

            connection.commit()
            connection.close()

            return redirect("/admin/employees")

        except sqlite3.IntegrityError:

            connection.close()

            return "An employee with this PIN already exists.", 400


    designations = connection.execute("""
        SELECT id, name
        FROM designations
        WHERE is_active = 1
        ORDER BY name
    """).fetchall()


    units = connection.execute("""
        SELECT id, name, unit_type
        FROM organizational_units
        WHERE is_active = 1
          AND unit_type != 'Authority'
        ORDER BY name
    """).fetchall()


    connection.close()

    return render_template(
        "add_employee.html",
        designations=designations,
        units=units
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

@app.route("/admin/employees/edit/<int:employee_id>", methods=["GET", "POST"])
def edit_employee(employee_id):

    connection = get_db_connection()

    employee = connection.execute("""
        SELECT *
        FROM employees
        WHERE id = ?
    """, (employee_id,)).fetchone()

    if employee is None:
        connection.close()
        return "Employee not found", 404


    if request.method == "POST":

        name = request.form["name"].strip()
        designation_id = request.form["designation_id"]
        organizational_unit_id = request.form["organizational_unit_id"]
        extension_number = request.form.get("extension_number", "").strip()

        connection.execute("""
            UPDATE employees
            SET name = ?,
                designation_id = ?,
                organizational_unit_id = ?,
                extension_number = ?
            WHERE id = ?
        """, (
            name,
            designation_id,
            organizational_unit_id,
            extension_number,
            employee_id
        ))

        connection.commit()
        connection.close()

        return redirect("/admin/employees")


    designations = connection.execute("""
        SELECT id, name
        FROM designations
        WHERE is_active = 1
        ORDER BY name
    """).fetchall()


    units = connection.execute("""
        SELECT id, name
        FROM organizational_units
        WHERE is_active = 1
          AND unit_type != 'Authority'
        ORDER BY name
    """).fetchall()


    connection.close()

    return render_template(
        "edit_employee.html",
        employee=employee,
        designations=designations,
        units=units
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