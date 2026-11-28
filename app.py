from functools import wraps
from flask import Flask, render_template, abort, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from database import get_connection

app = Flask(__name__)
app.config.from_object(Config)


def role_required(*allowed_roles):
    """Only let logged-in users with an allowed role open the page."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                flash("Please log in to continue.", "error")
                return redirect(url_for("login"))
            if session.get("role") not in allowed_roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator

# ---------------- PUBLIC PAGES ----------------

@app.route("/")
def home():
    connection = get_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, name, description, image_filename FROM clubs ORDER BY id LIMIT 3")
        clubs = cursor.fetchall()

        cursor.execute(
            "SELECT id, title, event_date, location, image_filename "
            "FROM events WHERE event_date >= NOW() ORDER BY event_date LIMIT 3"
        )
        events = cursor.fetchall()
    connection.close()

    return render_template("public/home.html", clubs=clubs, events=events)


@app.route("/clubs")
def clubs_page():
    connection = get_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, name, description, category, image_filename FROM clubs ORDER BY name")
        clubs = cursor.fetchall()
    connection.close()

    return render_template("public/clubs.html", clubs=clubs)


@app.route("/clubs/<int:club_id>")
def club_details(club_id):
    connection = get_connection()
    membership_status = None
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, name, description, category, image_filename FROM clubs WHERE id = %s",
            (club_id,),
        )
        club = cursor.fetchone()

        if club is None:
            connection.close()
            abort(404)

        cursor.execute(
            "SELECT id, title, event_date, location, image_filename "
            "FROM events WHERE club_id = %s AND event_date >= NOW() ORDER BY event_date",
            (club_id,),
        )
        events = cursor.fetchall()

        if session.get("role") == "student":
            cursor.execute(
                "SELECT status FROM memberships WHERE user_id = %s AND club_id = %s",
                (session["user_id"], club_id),
            )
            row = cursor.fetchone()
            if row:
                membership_status = row["status"]
    connection.close()

    return render_template(
        "public/club_details.html",
        club=club,
        events=events,
        membership_status=membership_status,
    )

@app.route("/events")
def events_page():
    connection = get_connection()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT e.id, e.title, e.event_date, e.location, e.image_filename, c.name AS club_name "
            "FROM events e JOIN clubs c ON e.club_id = c.id "
            "WHERE e.event_date >= NOW() ORDER BY e.event_date"
        )
        events = cursor.fetchall()
    connection.close()

    return render_template("public/events.html", events=events)


@app.route("/events/<int:event_id>")
def event_details(event_id):
    connection = get_connection()
    is_registered = False
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT e.id, e.title, e.description, e.event_date, e.location, e.image_filename, "
            "c.id AS club_id, c.name AS club_name "
            "FROM events e JOIN clubs c ON e.club_id = c.id WHERE e.id = %s",
            (event_id,),
        )
        event = cursor.fetchone()

        if event is not None and session.get("role") == "student":
            cursor.execute(
                "SELECT id FROM event_registrations WHERE event_id = %s AND user_id = %s",
                (event_id, session["user_id"]),
            )
            is_registered = cursor.fetchone() is not None
    connection.close()

    if event is None:
        abort(404)

    return render_template("public/event_details.html", event=event, is_registered=is_registered)


@app.route("/about")
def about():
    return render_template("public/about.html")


# ---------------- AUTHENTICATION ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        student_number = request.form.get("student_number", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        error = None
        if not full_name or not email or not password:
            error = "Please fill in all required fields."
        elif "@" not in email:
            error = "Please enter a valid email address."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm_password:
            error = "Passwords do not match."

        if error is None:
            connection = get_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                if cursor.fetchone():
                    error = "An account with this email already exists."
                else:
                    cursor.execute(
                        "INSERT INTO users (full_name, email, password_hash, role, student_number) "
                        "VALUES (%s, %s, %s, 'student', %s)",
                        (full_name, email, generate_password_hash(password), student_number or None),
                    )
                    connection.commit()
            connection.close()

        if error is None:
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))

        flash(error, "error")

    return render_template("auth/register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, full_name, password_hash, role, status FROM users WHERE email = %s",
                (email,),
            )
            user = cursor.fetchone()
        connection.close()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
        elif user["status"] != "active":
            flash("Your account is inactive. Please contact the administrator.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["full_name"]
            session["role"] = user["role"]
            flash("Welcome back, " + user["full_name"] + "!", "success")
            if user["role"] == "student":
                return redirect(url_for("student_dashboard"))
            return redirect(url_for("home"))
    return render_template("auth/login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))

# ---------------- STUDENT PAGES ----------------

@app.route("/student/dashboard")
@role_required("student")
def student_dashboard():
    user_id = session["user_id"]
    connection = get_connection()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS total FROM memberships WHERE user_id = %s AND status = 'approved'",
            (user_id,),
        )
        joined_clubs = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT COUNT(*) AS total FROM memberships WHERE user_id = %s AND status = 'pending'",
            (user_id,),
        )
        pending_requests = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT COUNT(*) AS total FROM event_registrations WHERE user_id = %s",
            (user_id,),
        )
        registered_events = cursor.fetchone()["total"]
    connection.close()

    return render_template(
        "student/dashboard.html",
        joined_clubs=joined_clubs,
        pending_requests=pending_requests,
        registered_events=registered_events,
    )

@app.route("/clubs/<int:club_id>/join", methods=["POST"])
@role_required("student")
def join_club(club_id):
    connection = get_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM clubs WHERE id = %s", (club_id,))
        if cursor.fetchone() is None:
            connection.close()
            abort(404)

        cursor.execute(
            "SELECT id FROM memberships WHERE user_id = %s AND club_id = %s",
            (session["user_id"], club_id),
        )
        if cursor.fetchone():
            flash("You have already sent a request or joined this club.", "error")
        else:
            cursor.execute(
                "INSERT INTO memberships (user_id, club_id) VALUES (%s, %s)",
                (session["user_id"], club_id),
            )
            connection.commit()
            flash("Your join request has been sent!", "success")
    connection.close()

    return redirect(url_for("club_details", club_id=club_id))


@app.route("/student/my-clubs")
@role_required("student")
def my_clubs():
    connection = get_connection()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT m.status, m.requested_at, c.id AS club_id, c.name, c.category, c.image_filename "
            "FROM memberships m JOIN clubs c ON m.club_id = c.id "
            "WHERE m.user_id = %s ORDER BY m.requested_at DESC",
            (session["user_id"],),
        )
        memberships = cursor.fetchall()
    connection.close()

    return render_template("student/my_clubs.html", memberships=memberships)

@app.route("/events/<int:event_id>/register", methods=["POST"])
@role_required("student")
def register_for_event(event_id):
    connection = get_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, event_date FROM events WHERE id = %s", (event_id,))
        event = cursor.fetchone()
        if event is None:
            connection.close()
            abort(404)

        cursor.execute(
            "SELECT id FROM event_registrations WHERE event_id = %s AND user_id = %s",
            (event_id, session["user_id"]),
        )
        if cursor.fetchone():
            flash("You are already registered for this event.", "error")
        else:
            cursor.execute(
                "INSERT INTO event_registrations (event_id, user_id) VALUES (%s, %s)",
                (event_id, session["user_id"]),
            )
            connection.commit()
            flash("You have registered for the event!", "success")
    connection.close()

    return redirect(url_for("event_details", event_id=event_id))


@app.route("/student/my-events")
@role_required("student")
def my_events():
    connection = get_connection()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT r.registered_at, e.id AS event_id, e.title, e.event_date, e.location, "
            "e.image_filename, c.name AS club_name "
            "FROM event_registrations r "
            "JOIN events e ON r.event_id = e.id "
            "JOIN clubs c ON e.club_id = c.id "
            "WHERE r.user_id = %s ORDER BY e.event_date",
            (session["user_id"],),
        )
        registrations = cursor.fetchall()
    connection.close()

    return render_template("student/my_events.html", registrations=registrations)

@app.route("/student/announcements")
@role_required("student")
def student_announcements():
    connection = get_connection()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT a.title, a.content, a.created_at, c.id AS club_id, c.name AS club_name "
            "FROM announcements a JOIN clubs c ON a.club_id = c.id "
            "ORDER BY a.created_at DESC"
        )
        announcements = cursor.fetchall()
    connection.close()

    return render_template("student/announcements.html", announcements=announcements)


@app.route("/student/profile", methods=["GET", "POST"])
@role_required("student")
def student_profile():
    user_id = session["user_id"]
    connection = get_connection()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        student_number = request.form.get("student_number", "").strip()

        if not full_name:
            flash("Full name cannot be empty.", "error")
        else:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET full_name = %s, phone = %s, student_number = %s WHERE id = %s",
                    (full_name, phone or None, student_number or None, user_id),
                )
                connection.commit()
            session["user_name"] = full_name
            flash("Profile updated successfully.", "success")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT full_name, email, phone, student_number, created_at FROM users WHERE id = %s",
            (user_id,),
        )
        user = cursor.fetchone()
    connection.close()

    return render_template("student/profile.html", user=user)



if __name__ == "__main__":
    app.run(debug=True)