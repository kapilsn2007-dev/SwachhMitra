import sqlite3
from functools import wraps
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone, timedelta

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from PIL import Image
import os


# =========================================================
# APP SETUP
# =========================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "swachhmitra-secret-key"
)

BASE_DIR = Path(__file__).resolve().parent

DATABASE = str(BASE_DIR / "swachhmitra.db")

UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"

UPLOAD_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)

app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


# =========================================================
# CONSTANTS
# =========================================================

ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "webp"
}

ADMIN_EMAIL = "admin@swachhmitra.com"

ADMIN_PASSWORD = "admin123"


# =========================================================
# AI CLASSIFIER
# =========================================================

# Render free instances have limited RAM.
# Therefore the heavy AI model is disabled on Render.

if os.environ.get("RENDER"):

    classifier = None

else:

    try:

        from transformers import pipeline

        classifier = pipeline(
            "image-classification",
            model="yangy50/garbage-classification"
        )

    except Exception:

        classifier = None


WASTE_MAP = {
    "plastic": "Plastic Waste",
    "paper": "Dry Waste",
    "cardboard": "Dry Waste",
    "glass": "Dry Waste",
    "metal": "Dry Waste",
    "trash": "Mixed Waste",
}


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db():

    if "db" not in g:

        g.db = sqlite3.connect(
            DATABASE
        )

        g.db.row_factory = sqlite3.Row

    return g.db


@app.teardown_appcontext
def close_db(error=None):

    db = g.pop(
        "db",
        None
    )

    if db is not None:

        db.close()


# =========================================================
# INITIALIZE DATABASE
# =========================================================

def init_db():

    db = sqlite3.connect(
        DATABASE
    )

    # =====================================================
    # USERS TABLE
    # =====================================================

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            address TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            profile_image TEXT DEFAULT '',
            is_admin INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )

    # =====================================================
    # REPORTS TABLE
    # =====================================================

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_code TEXT UNIQUE NOT NULL,
            user_id INTEGER,
            waste_type TEXT DEFAULT '',
            description TEXT DEFAULT '',
            image_filename TEXT DEFAULT '',
            address TEXT DEFAULT '',
            latitude TEXT DEFAULT '',
            longitude TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Reported',
            is_anonymous INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    # =====================================================
    # DUSTBINS TABLE
    # =====================================================

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS dustbins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT DEFAULT '',
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accepted_waste TEXT DEFAULT '',
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )

    # =====================================================
    # DEMO / COMMUNITY DUSTBIN LOCATIONS
    # =====================================================
    #
    # These are demo locations for the college project.
    # They should NOT be presented as officially installed
    # PCMC dustbins unless independently verified.
    #
    # =====================================================

    demo_dustbins = [

        (
            "Demo Community Point 1 - Pimpri",
            "Pimpri area",
            18.6298,
            73.7997,
            "Dry Waste, Plastic",
            "Demo location for college project."
        ),

        (
            "Demo Community Point 2 - Pimpri Market",
            "Pimpri Market area",
            18.6277,
            73.8030,
            "Dry Waste, Plastic",
            "Demo location for college project."
        ),

        (
            "Demo Community Point 3 - Pimpri Railway Area",
            "Near Pimpri Railway Station",
            18.6232,
            73.8020,
            "Dry Waste, Plastic, Mixed Waste",
            "Demo location for college project."
        ),

        (
            "Demo Community Point 4 - Sant Tukaram Nagar",
            "Sant Tukaram Nagar",
            18.6205,
            73.8205,
            "Dry Waste, Plastic",
            "Demo location for college project."
        ),

        (
            "Demo Community Point 5 - YCM Area",
            "YCM Hospital area",
            18.6218,
            73.8210,
            "Dry Waste, Plastic",
            "Demo location for college project."
        ),

        (
            "Demo Community Point 6 - Vallabh Nagar",
            "Vallabh Nagar, Pimpri",
            18.6258,
            73.8120,
            "Dry Waste, Plastic",
            "Demo location for college project."
        ),

        (
            "Demo Community Point 7 - Pimpri Camp",
            "Pimpri Camp area",
            18.6270,
            73.8090,
            "Dry Waste, Mixed Waste",
            "Demo location for college project."
        ),

        (
            "Demo Community Point 8 - Nehru Nagar",
            "Nehru Nagar, Pimpri",
            18.6370,
            73.8050,
            "Dry Waste, Plastic",
            "Demo location for college project."
        ),

        (
            "Demo Community Point 9 - Kasarwadi",
            "Kasarwadi area",
            18.6085,
            73.8205,
            "Dry Waste, Plastic",
            "Demo location for college project."
        ),

        (
            "Demo Community Point 10 - Pimpri-Bopodi Road",
            "Pimpri-Bopodi Road area",
            18.6025,
            73.8125,
            "Dry Waste, Plastic",
            "Demo location for college project."
        ),

        (
            "Demo Community Point 11 - Sant Tukaram Nagar East",
            "Sant Tukaram Nagar East",
            18.6190,
            73.8250,
            "Dry Waste, Plastic, E-Waste",
            "Demo location for college project."
        ),

        (
            "Demo Community Point 12 - Pimpri East",
            "Pimpri East area",
            18.6305,
            73.8110,
            "Dry Waste, Plastic",
            "Demo location for college project."
        ),
    ]

    # =====================================================
    # INSERT DEMO DUSTBINS ONLY IF TABLE IS EMPTY
    # =====================================================

    existing_dustbins = db.execute(
        "SELECT COUNT(*) FROM dustbins"
    ).fetchone()[0]

    if existing_dustbins == 0:

        db.executemany(
            """
            INSERT INTO dustbins (
                name,
                address,
                latitude,
                longitude,
                accepted_waste,
                description
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            demo_dustbins
        )

        db.commit()

    # =====================================================
    # BACKWARD COMPATIBILITY FOR USERS TABLE
    # =====================================================

    user_columns = [
        row[1]
        for row in db.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    ]

    if "address" not in user_columns:

        db.execute(
            """
            ALTER TABLE users
            ADD COLUMN address TEXT DEFAULT ''
            """
        )

    if "phone" not in user_columns:

        db.execute(
            """
            ALTER TABLE users
            ADD COLUMN phone TEXT DEFAULT ''
            """
        )

    if "profile_image" not in user_columns:

        db.execute(
            """
            ALTER TABLE users
            ADD COLUMN profile_image TEXT DEFAULT ''
            """
        )

    # =====================================================
    # BACKWARD COMPATIBILITY FOR REPORTS TABLE
    # =====================================================

    report_columns = [
        row[1]
        for row in db.execute(
            "PRAGMA table_info(reports)"
        ).fetchall()
    ]

    if "latitude" not in report_columns:

        db.execute(
            """
            ALTER TABLE reports
            ADD COLUMN latitude TEXT DEFAULT ''
            """
        )

    if "longitude" not in report_columns:

        db.execute(
            """
            ALTER TABLE reports
            ADD COLUMN longitude TEXT DEFAULT ''
            """
        )

    if "is_anonymous" not in report_columns:

        db.execute(
            """
            ALTER TABLE reports
            ADD COLUMN is_anonymous INTEGER DEFAULT 0
            """
        )

    # =====================================================
    # DEFAULT ADMIN
    # =====================================================

    admin = db.execute(
        """
        SELECT id
        FROM users
        WHERE email = ?
        """,
        (ADMIN_EMAIL,)
    ).fetchone()

    if not admin:

        db.execute(
            """
            INSERT INTO users (
                name,
                email,
                password_hash,
                is_admin
            )
            VALUES (?, ?, ?, 1)
            """,
            (
                "Administrator",
                ADMIN_EMAIL,
                generate_password_hash(
                    ADMIN_PASSWORD
                )
            )
        )

    db.commit()

    db.close()


# =========================================================
# LOGIN REQUIRED
# =========================================================

def login_required(view):

    @wraps(view)
    def wrapped_view(*args, **kwargs):

        if "user_id" not in session:

            flash(
                "Please login first.",
                "warning"
            )

            return redirect(
                url_for("login")
            )

        return view(
            *args,
            **kwargs
        )

    return wrapped_view


# =========================================================
# ADMIN REQUIRED
# =========================================================

def admin_required(view):

    @wraps(view)
    def wrapped_view(*args, **kwargs):

        if "user_id" not in session:

            flash(
                "Please login first.",
                "warning"
            )

            return redirect(
                url_for("login")
            )

        db = get_db()

        user = db.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            """,
            (session["user_id"],)
        ).fetchone()

        if not user or not user["is_admin"]:

            flash(
                "Administrator access required.",
                "danger"
            )

            return redirect(
                url_for("dashboard")
            )

        return view(
            *args,
            **kwargs
        )

    return wrapped_view


# =========================================================
# TRANSLATIONS
# =========================================================

TRANSLATIONS = {

    "en": {

        "home": "Home",
        "admin_dashboard": "Admin Dashboard",
        "dashboard": "Dashboard",
        "report_waste": "Report Waste",
        "profile": "My Profile",
        "logout": "Logout",
        "login": "Login",
        "register": "Register",
        "welcome": "Welcome to SwachhMitra",
        "dustbins": "Dustbins",
        "community_survey": "Community Survey",

    },

    "mr": {

        "home": "मुख्यपृष्ठ",
        "admin_dashboard": "प्रशासक डॅशबोर्ड",
        "dashboard": "डॅशबोर्ड",
        "report_waste": "कचरा नोंदवा",
        "profile": "माझे प्रोफाइल",
        "logout": "लॉगआउट",
        "login": "लॉगिन",
        "register": "नोंदणी",
        "welcome": "स्वच्छमित्रमध्ये आपले स्वागत",
        "dustbins": "कचरापेट्या",
        "community_survey": "समुदाय सर्वेक्षण",

    },

    "hi": {

        "home": "मुख्य पृष्ठ",
        "admin_dashboard": "प्रशासक डैशबोर्ड",
        "dashboard": "डैशबोर्ड",
        "report_waste": "कचरा रिपोर्ट करें",
        "profile": "मेरी प्रोफ़ाइल",
        "logout": "लॉगआउट",
        "login": "लॉगिन",
        "register": "पंजीकरण",
        "welcome": "स्वच्छमित्र में आपका स्वागत है",
        "dustbins": "कूड़ेदान",
        "community_survey": "समुदाय सर्वेक्षण",

    }
}


# =========================================================
# GLOBAL TEMPLATE VARIABLES
# =========================================================

@app.context_processor
def inject_globals():

    language = session.get(
        "language",
        "mr"
    )

    return {
        "current_language": language,
        "t": TRANSLATIONS.get(
            language,
            TRANSLATIONS["mr"]
        )
    }


# =========================================================
# IST DATETIME FILTER
# =========================================================

@app.template_filter("ist_datetime")
def to_ist(value):

    if not value:

        return ""

    try:

        utc_time = datetime.strptime(
            value,
            "%Y-%m-%d %H:%M:%S"
        ).replace(
            tzinfo=timezone.utc
        )

        ist_time = (
            utc_time
            + timedelta(
                hours=5,
                minutes=30
            )
        )

        return ist_time.strftime(
            "%d-%m-%Y %I:%M:%S %p IST"
        )

    except (
        ValueError,
        TypeError
    ):

        return value


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template(
        "home.html"
    )


# =========================================================
# LANGUAGE
# =========================================================

@app.route(
    "/set-language/<language>"
)
def set_language(language):

    if language not in TRANSLATIONS:

        language = "mr"

    session["language"] = language

    return redirect(
        request.referrer
        or url_for("home")
    )


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

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

        address = request.form.get(
            "address",
            ""
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        if not name or not email or not password:

            flash(
                "Please fill all required fields.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        db = get_db()

        existing = db.execute(
            """
            SELECT id
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        if existing:

            flash(
                "Email already registered.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        db.execute(
            """
            INSERT INTO users (
                name,
                email,
                password_hash,
                address,
                phone
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                name,
                email,
                generate_password_hash(password),
                address,
                phone
            )
        )

        db.commit()

        flash(
            "Registration successful. Please login.",
            "success"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "register.html"
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        db = get_db()

        user = db.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        if (
            user
            and check_password_hash(
                user["password_hash"],
                password
            )
        ):

            session.clear()

            session["user_id"] = user["id"]

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Invalid email or password.",
            "danger"
        )

    return render_template(
        "login.html"
    )


# =========================================================
# ADMIN LOGIN
# =========================================================

@app.route(
    "/admin-login",
    methods=["GET", "POST"]
)
def admin_login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        db = get_db()

        user = db.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            AND is_admin = 1
            """,
            (email,)
        ).fetchone()

        if (
            user
            and check_password_hash(
                user["password_hash"],
                password
            )
        ):

            session.clear()

            session["user_id"] = user["id"]

            return redirect(
                url_for("admin_dashboard")
            )

        flash(
            "Invalid administrator credentials.",
            "danger"
        )

    return render_template(
        "admin_login.html"
    )


# =========================================================
# USER DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():

    db = get_db()

    user = db.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    reports = db.execute(
        """
        SELECT *
        FROM reports
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],)
    ).fetchall()

    return render_template(
        "user_dashboard.html",
        user=user,
        reports=reports
    )


# =========================================================
# PROFILE
# =========================================================

@app.route(
    "/profile",
    methods=["GET", "POST"]
)
@login_required
def profile():

    db = get_db()

    user = db.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        address = request.form.get(
            "address",
            ""
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        image_filename = user["profile_image"]

        profile_image = request.files.get(
            "profile_image"
        )

        if (
            profile_image
            and profile_image.filename
        ):

            extension = (
                profile_image.filename
                .rsplit(".", 1)[-1]
                .lower()
            )

            if extension in ALLOWED_EXTENSIONS:

                filename = (
                    f"profile_{user['id']}_"
                    f"{uuid4().hex}.{extension}"
                )

                safe_filename = secure_filename(
                    filename
                )

                profile_image.save(
                    UPLOAD_FOLDER
                    / safe_filename
                )

                image_filename = safe_filename

        db.execute(
            """
            UPDATE users
            SET
                name = ?,
                address = ?,
                phone = ?,
                profile_image = ?
            WHERE id = ?
            """,
            (
                name,
                address,
                phone,
                image_filename,
                user["id"]
            )
        )

        db.commit()

        flash(
            "Profile updated successfully.",
            "success"
        )

        return redirect(
            url_for("profile")
        )

    return render_template(
        "profile.html",
        user=user
    )


# =========================================================
# REPORT WASTE
# =========================================================

@app.route(
    "/report",
    methods=["GET", "POST"]
)
@login_required
def report_waste():

    if request.method == "POST":

        waste_type = request.form.get(
            "waste_type",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        address = request.form.get(
            "address",
            ""
        ).strip()

        latitude = request.form.get(
            "latitude",
            ""
        ).strip()

        longitude = request.form.get(
            "longitude",
            ""
        ).strip()

        is_anonymous = 1 if request.form.get(
            "anonymous"
        ) else 0

        image_filename = ""

        image = request.files.get(
            "image"
        )

        # =================================================
        # IMAGE UPLOAD
        # =================================================

        if image and image.filename:

            extension = (
                image.filename
                .rsplit(".", 1)[-1]
                .lower()
            )

            if extension not in ALLOWED_EXTENSIONS:

                flash(
                    "Invalid image format.",
                    "danger"
                )

                return render_template(
                    "report.html"
                )

            image_filename = (
                f"{uuid4().hex}.{extension}"
            )

            image_filename = secure_filename(
                image_filename
            )

            image_path = (
                UPLOAD_FOLDER
                / image_filename
            )

            image.save(
                image_path
            )

            # =============================================
            # AI CLASSIFICATION
            # =============================================

            if classifier is not None:

                try:

                    pil_image = Image.open(
                        image_path
                    ).convert("RGB")

                    predictions = classifier(
                        pil_image
                    )

                    if predictions:

                        top_label = (
                            predictions[0]["label"]
                            .lower()
                        )

                        detected_type = WASTE_MAP.get(
                            top_label
                        )

                        if detected_type:

                            waste_type = detected_type

                except Exception:

                    pass

        # =================================================
        # REPORT CODE
        # =================================================

        report_code = (
            "SM-"
            + datetime.now().strftime(
                "%Y%m%d"
            )
            + "-"
            + uuid4().hex[:6].upper()
        )

        db = get_db()

        db.execute(
            """
            INSERT INTO reports (
                report_code,
                user_id,
                waste_type,
                description,
                image_filename,
                address,
                latitude,
                longitude,
                status,
                is_anonymous
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_code,
                session["user_id"],
                waste_type,
                description,
                image_filename,
                address,
                latitude,
                longitude,
                "Reported",
                is_anonymous
            )
        )

        db.commit()

        flash(
            f"Report submitted successfully. "
            f"Report ID: {report_code}",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "report.html"
    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin")
@admin_required
def admin_dashboard():

    db = get_db()

    reports = db.execute(
        """
        SELECT
            reports.*,
            users.name AS user_name,
            users.email AS user_email
        FROM reports
        LEFT JOIN users
            ON reports.user_id = users.id
        ORDER BY reports.id DESC
        """
    ).fetchall()

    total_reports = db.execute(
        "SELECT COUNT(*) FROM reports"
    ).fetchone()[0]

    reported_count = db.execute(
        """
        SELECT COUNT(*)
        FROM reports
        WHERE status = 'Reported'
        """
    ).fetchone()[0]

    cleaned_count = db.execute(
        """
        SELECT COUNT(*)
        FROM reports
        WHERE status = 'Cleaned'
        """
    ).fetchone()[0]

    closed_count = db.execute(
        """
        SELECT COUNT(*)
        FROM reports
        WHERE status = 'Closed'
        """
    ).fetchone()[0]

    dustbin_count = db.execute(
        """
        SELECT COUNT(*)
        FROM dustbins
        """
    ).fetchone()[0]

    return render_template(
        "admin_dashboard.html",
        reports=reports,
        total_reports=total_reports,
        reported_count=reported_count,
        cleaned_count=cleaned_count,
        closed_count=closed_count,
        dustbin_count=dustbin_count
    )


# =========================================================
# UPDATE REPORT STATUS
# =========================================================

@app.route(
    "/admin/report/<int:report_id>/status",
    methods=["POST"]
)
@admin_required
def update_status(report_id):

    status = request.form.get(
        "status",
        ""
    ).strip()

    allowed_statuses = {
        "Reported",
        "Verified",
        "Assigned",
        "Cleaning in Progress",
        "Cleaned",
        "Closed"
    }

    if status not in allowed_statuses:

        flash(
            "Invalid status.",
            "danger"
        )

        return redirect(
            url_for("admin_dashboard")
        )

    db = get_db()

    db.execute(
        """
        UPDATE reports
        SET status = ?
        WHERE id = ?
        """,
        (
            status,
            report_id
        )
    )

    db.commit()

    flash(
        "Report status updated.",
        "success"
    )

    return redirect(
        url_for("admin_dashboard")
    )


# =========================================================
# REPORT STATUS
# =========================================================

@app.route(
    "/report/<int:report_id>/status"
)
@login_required
def report_status(report_id):

    db = get_db()

    report = db.execute(
        """
        SELECT *
        FROM reports
        WHERE id = ?
        """,
        (report_id,)
    ).fetchone()

    if not report:

        flash(
            "Report not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    user = db.execute(
        """
        SELECT is_admin
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    if (
        report["user_id"] != session["user_id"]
        and (
            not user
            or not user["is_admin"]
        )
    ):

        flash(
            "You do not have permission to view this report.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "status.html",
        report=report
    )


# =========================================================
# CERTIFICATE
# =========================================================

@app.route("/certificate")
@login_required
def certificate():

    db = get_db()

    user = db.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    return render_template(
        "certificate.html",
        user=user
    )


# =========================================================
# DUSTBINS
# =========================================================

@app.route("/dustbins")
@login_required
def dustbins():

    db = get_db()

    dustbin_list = db.execute(
        """
        SELECT *
        FROM dustbins
        ORDER BY id DESC
        """
    ).fetchall()

    return render_template(
        "dustbins.html",
        dustbins=dustbin_list
    )


# =========================================================
# ADD DUSTBIN
# =========================================================

@app.route(
    "/admin/dustbin/add",
    methods=["GET", "POST"]
)
@admin_required
def add_dustbin():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        address = request.form.get(
            "address",
            ""
        ).strip()

        latitude = request.form.get(
            "latitude",
            ""
        ).strip()

        longitude = request.form.get(
            "longitude",
            ""
        ).strip()

        accepted_waste = request.form.get(
            "accepted_waste",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        if (
            not name
            or not latitude
            or not longitude
        ):

            flash(
                "Name, latitude and longitude are required.",
                "danger"
            )

            return render_template(
                "add_dustbin.html"
            )

        try:

            latitude = float(
                latitude
            )

            longitude = float(
                longitude
            )

        except ValueError:

            flash(
                "Latitude and longitude must be valid numbers.",
                "danger"
            )

            return render_template(
                "add_dustbin.html"
            )

        db = get_db()

        db.execute(
            """
            INSERT INTO dustbins (
                name,
                address,
                latitude,
                longitude,
                accepted_waste,
                description
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                address,
                latitude,
                longitude,
                accepted_waste,
                description
            )
        )

        db.commit()

        flash(
            "Dustbin location added successfully.",
            "success"
        )

        return redirect(
            url_for("dustbins")
        )

    return render_template(
        "add_dustbin.html"
    )


# =========================================================
# DELETE DUSTBIN
# =========================================================

@app.route(
    "/admin/dustbin/<int:dustbin_id>/delete",
    methods=["POST"]
)
@admin_required
def delete_dustbin(dustbin_id):

    db = get_db()

    db.execute(
        """
        DELETE FROM dustbins
        WHERE id = ?
        """,
        (dustbin_id,)
    )

    db.commit()

    flash(
        "Dustbin location deleted.",
        "success"
    )

    return redirect(
        url_for("dustbins")
    )


# =========================================================
# COMMUNITY SURVEY
# =========================================================

@app.route("/community-survey")
@login_required
def community_survey():

    return render_template(
        "community_survey.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(
        url_for("home")
    )


# =========================================================
# INITIALIZE DATABASE
# =========================================================

init_db()


# =========================================================
# RUN APP
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )
