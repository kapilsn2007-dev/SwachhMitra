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

from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)

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

DATABASE = str(
    BASE_DIR / "swachhmitra.db"
)

UPLOAD_FOLDER = (
    BASE_DIR / "static" / "uploads"
)

UPLOAD_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)

app.config["UPLOAD_FOLDER"] = str(
    UPLOAD_FOLDER
)

app.config["MAX_CONTENT_LENGTH"] = (
    5 * 1024 * 1024
)


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
#
# Heavy Hugging Face model is disabled on Render because
# Render free instances have limited memory.
#
# Locally the classifier can still be loaded.
# =========================================================

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
# DATABASE
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
# DATABASE INITIALIZATION
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
            full_name TEXT NOT NULL,
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
            anonymous INTEGER DEFAULT 0,
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
    # BACKWARD COMPATIBILITY FOR USERS
    # =====================================================

    user_columns = [
        row[1]
        for row in db.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    ]

    # Old database may have "name"
    # New templates use "full_name".

    if "full_name" not in user_columns:

        db.execute(
            """
            ALTER TABLE users
            ADD COLUMN full_name TEXT DEFAULT ''
            """
        )

        if "name" in user_columns:

            db.execute(
                """
                UPDATE users
                SET full_name = name
                WHERE full_name = ''
                """
            )

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

    if "is_admin" not in user_columns:

        db.execute(
            """
            ALTER TABLE users
            ADD COLUMN is_admin INTEGER DEFAULT 0
            """
        )

    # =====================================================
    # BACKWARD COMPATIBILITY FOR REPORTS
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

    if "anonymous" not in report_columns:

        db.execute(
            """
            ALTER TABLE reports
            ADD COLUMN anonymous INTEGER DEFAULT 0
            """
        )

        # If old database has is_anonymous,
        # copy the values.

        if "is_anonymous" in report_columns:

            db.execute(
                """
                UPDATE reports
                SET anonymous = is_anonymous
                """
            )

    # =====================================================
    # DEMO DUSTBIN LOCATIONS
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
                full_name,
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
                url_for("user_dashboard")
            )

        return view(
            *args,
            **kwargs
        )

    return wrapped_view


# =========================================================
# LANGUAGES
# =========================================================

SUPPORTED_LANGUAGES = {
    "mr": "मराठी",
    "en": "English",
    "hi": "हिन्दी"
}


# =========================================================
# TRANSLATIONS
# =========================================================

TRANSLATIONS = {

    "en": {

        "SwachhMitra": "SwachhMitra",

        "home": "Home",
        "dashboard": "Dashboard",
        "admin_dashboard": "Admin Dashboard",

        "login": "Login",
        "register": "Register",
        "logout": "Logout",

        "admin_login": "Admin Login",
        "default_admin_account":
            "Default admin account: admin@swachhmitra.com",

        "admin_email": "Admin Email",
        "password": "Password",

        "user_login": "User Login",
        "user_registration": "User Registration",

        "email": "Email",
        "full_name": "Full Name",
        "phone_number": "Phone Number",
        "address_locality": "Address / Locality",

        "confirm_password": "Confirm Password",

        "new_user": "New user?",
        "register_here": "Register here",
        "already_account": "Already have an account?",
        "log_in": "Log in",

        "my_profile": "My Profile",
        "save_profile": "Save Profile",
        "view_profile": "View Profile",
        "profile_description":
            "View and update your personal information.",
        "email_cannot_change":
            "Email address cannot be changed.",
        "enter_phone":
            "Enter phone number",
        "enter_address":
            "Enter your address",
        "back_to_dashboard":
            "Back to Dashboard",

        "report_garbage": "Report Garbage",
        "report_garbage_help":
            "Submit a garbage report with details and location.",
        "report_description":
            "Report garbage in your locality and help keep the community clean.",

        "waste_type": "Waste Type",
        "select_waste_type":
            "Select waste type",

        "dry_waste": "Dry Waste",
        "wet_waste": "Wet Waste",
        "plastic_waste": "Plastic Waste",
        "e_waste": "E-Waste",
        "construction": "Construction Waste",
        "medical": "Medical Waste",
        "mixed_waste": "Mixed Waste",
        "other": "Other",

        "garbage_image":
            "Garbage Image",
        "ai_detection_note":
            "AI can help identify the waste type from the uploaded image.",
        "upload_clear_photo":
            "Upload a clear photo.",
        "maximum_size":
            "Maximum size: 5 MB.",

        "description": "Description",
        "description_placeholder":
            "Describe the garbage problem...",

        "location_locality":
            "Location / Locality",
        "location_example":
            "Example: Pimpri, Pune",

        "latitude": "Latitude",
        "longitude": "Longitude",
        "optional": "Optional",

        "anonymous_report":
            "Submit this report anonymously",

        "submit_garbage_report":
            "Submit Garbage Report",

        "garbage_reports":
            "My Garbage Reports",

        "report_id": "Report ID",
        "location": "Location",
        "status": "Status",
        "date": "Date",

        "reported": "Reported",
        "verified": "Verified",
        "assigned": "Assigned",
        "cleaning_in_progress":
            "Cleaning in Progress",
        "cleaned": "Cleaned",
        "closed": "Closed",

        "not_provided": "Not provided",
        "no_reports": "You have not submitted any reports yet.",
        "first_report":
            "Submit Your First Report",

        "home_description":
            "A community-driven platform for reporting and managing waste.",
        "home_features":
            "Report garbage, track its status and help create a cleaner locality.",

        "create_account":
            "Create Account",
        "go_to_dashboard":
            "Go to Dashboard",
        "go_to_admin_dashboard":
            "Go to Admin Dashboard",

        "admin_welcome":
            "Welcome",
        "manage_reports":
            "Manage garbage reports submitted by users.",

        "registered_users":
            "Registered Users",
        "total_reports":
            "Total Reports",
        "awaiting_action":
            "Awaiting Action",
        "cleaned_reports":
            "Cleaned Reports",

        "garbage_report_management":
            "Garbage Report Management",

        "image": "Image",
        "reporter": "Reporter",
        "current_status":
            "Current Status",
        "update_status":
            "Update Status",
        "view_image":
            "View Image",
        "no_image":
            "No image",
        "anonymous":
            "Anonymous",
        "unknown_user":
            "Unknown User",
        "new_report_status":
            "New report status",
        "save_status":
            "Save Status",

        "no_garbage_reports":
            "No garbage reports",
        "submitted_reports_here":
            "Submitted garbage reports will appear here.",

    },

    "mr": {

        "SwachhMitra": "स्वच्छमित्र",

        "home": "मुख्यपृष्ठ",
        "dashboard": "डॅशबोर्ड",
        "admin_dashboard": "प्रशासक डॅशबोर्ड",

        "login": "लॉगिन",
        "register": "नोंदणी",
        "logout": "लॉगआउट",

        "admin_login": "प्रशासक लॉगिन",
        "default_admin_account":
            "डीफॉल्ट प्रशासक खाते: admin@swachhmitra.com",

        "admin_email": "प्रशासक ईमेल",
        "password": "पासवर्ड",

        "user_login": "वापरकर्ता लॉगिन",
        "user_registration": "वापरकर्ता नोंदणी",

        "email": "ईमेल",
        "full_name": "पूर्ण नाव",
        "phone_number": "फोन नंबर",
        "address_locality": "पत्ता / परिसर",

        "confirm_password": "पासवर्डची पुष्टी करा",

        "new_user": "नवीन वापरकर्ता?",
        "register_here": "येथे नोंदणी करा",
        "already_account": "आधीच खाते आहे?",
        "log_in": "लॉगिन करा",

        "my_profile": "माझे प्रोफाइल",
        "save_profile": "प्रोफाइल जतन करा",
        "view_profile": "प्रोफाइल पहा",
        "profile_description":
            "आपली वैयक्तिक माहिती पहा आणि अपडेट करा.",
        "email_cannot_change":
            "ईमेल बदलता येणार नाही.",
        "enter_phone":
            "फोन नंबर टाका",
        "enter_address":
            "आपला पत्ता टाका",
        "back_to_dashboard":
            "डॅशबोर्डवर परत जा",

        "report_garbage": "कचरा नोंदवा",
        "report_garbage_help":
            "कचऱ्याची माहिती आणि स्थान देऊन अहवाल नोंदवा.",
        "report_description":
            "आपल्या परिसरातील कचरा नोंदवा आणि परिसर स्वच्छ ठेवण्यास मदत करा.",

        "waste_type": "कचऱ्याचा प्रकार",
        "select_waste_type":
            "कचऱ्याचा प्रकार निवडा",

        "dry_waste": "सुका कचरा",
        "wet_waste": "ओला कचरा",
        "plastic_waste": "प्लास्टिक कचरा",
        "e_waste": "ई-कचरा",
        "construction": "बांधकाम कचरा",
        "medical": "वैद्यकीय कचरा",
        "mixed_waste": "मिश्र कचरा",
        "other": "इतर",

        "garbage_image":
            "कचऱ्याचा फोटो",
        "ai_detection_note":
            "अपलोड केलेल्या फोटोमधून AI कचऱ्याचा प्रकार ओळखण्यास मदत करू शकते.",
        "upload_clear_photo":
            "स्वच्छ फोटो अपलोड करा.",
        "maximum_size":
            "कमाल आकार: 5 MB.",

        "description": "वर्णन",
        "description_placeholder":
            "कचऱ्याच्या समस्येचे वर्णन करा...",

        "location_locality":
            "स्थान / परिसर",
        "location_example":
            "उदा.: पिंपरी, पुणे",

        "latitude": "अक्षांश",
        "longitude": "रेखांश",
        "optional": "ऐच्छिक",

        "anonymous_report":
            "हा अहवाल अनामिक म्हणून नोंदवा",

        "submit_garbage_report":
            "कचरा अहवाल सबमिट करा",

        "garbage_reports":
            "माझे कचरा अहवाल",

        "report_id": "अहवाल क्रमांक",
        "location": "स्थान",
        "status": "स्थिती",
        "date": "दिनांक",

        "reported": "नोंदवले",
        "verified": "पडताळले",
        "assigned": "नियुक्त केले",
        "cleaning_in_progress":
            "साफसफाई सुरू",
        "cleaned": "साफ केले",
        "closed": "बंद",

        "not_provided": "दिलेली नाही",
        "no_reports":
            "आपण अद्याप कोणताही अहवाल नोंदवलेला नाही.",
        "first_report":
            "पहिला अहवाल नोंदवा",

        "home_description":
            "कचरा नोंदणी आणि व्यवस्थापनासाठी समुदाय-आधारित प्लॅटफॉर्म.",
        "home_features":
            "कचरा नोंदवा, त्याची स्थिती तपासा आणि स्वच्छ परिसर तयार करण्यात मदत करा.",

        "create_account":
            "खाते तयार करा",
        "go_to_dashboard":
            "डॅशबोर्डवर जा",
        "go_to_admin_dashboard":
            "प्रशासक डॅशबोर्डवर जा",

        "admin_welcome":
            "स्वागत",
        "manage_reports":
            "वापरकर्त्यांनी नोंदवलेल्या कचरा अहवालांचे व्यवस्थापन करा.",

        "registered_users":
            "नोंदणीकृत वापरकर्ते",
        "total_reports":
            "एकूण अहवाल",
        "awaiting_action":
            "कारवाईसाठी प्रतीक्षा",
        "cleaned_reports":
            "साफ केलेले अहवाल",

        "garbage_report_management":
            "कचरा अहवाल व्यवस्थापन",

        "image": "फोटो",
        "reporter": "अहवालकर्ता",
        "current_status":
            "सध्याची स्थिती",
        "update_status":
            "स्थिती अपडेट करा",
        "view_image":
            "फोटो पहा",
        "no_image":
            "फोटो नाही",
        "anonymous":
            "अनामिक",
        "unknown_user":
            "अज्ञात वापरकर्ता",
        "new_report_status":
            "नवीन अहवाल स्थिती",
        "save_status":
            "स्थिती जतन करा",

        "no_garbage_reports":
            "कचरा अहवाल नाहीत",
        "submitted_reports_here":
            "सबमिट केलेले कचरा अहवाल येथे दिसतील.",

    },

    "hi": {

        "SwachhMitra": "स्वच्छमित्र",

        "home": "मुख्य पृष्ठ",
        "dashboard": "डैशबोर्ड",
        "admin_dashboard": "प्रशासक डैशबोर्ड",

        "login": "लॉगिन",
        "register": "पंजीकरण",
        "logout": "लॉगआउट",

        "admin_login": "प्रशासक लॉगिन",
        "default_admin_account":
            "डिफ़ॉल्ट प्रशासक खाता: admin@swachhmitra.com",

        "admin_email": "प्रशासक ईमेल",
        "password": "पासवर्ड",

        "user_login": "उपयोगकर्ता लॉगिन",
        "user_registration": "उपयोगकर्ता पंजीकरण",

        "email": "ईमेल",
        "full_name": "पूरा नाम",
        "phone_number": "फोन नंबर",
        "address_locality": "पता / क्षेत्र",

        "confirm_password": "पासवर्ड की पुष्टि करें",

        "new_user": "नए उपयोगकर्ता?",
        "register_here": "यहाँ पंजीकरण करें",
        "already_account": "पहले से खाता है?",
        "log_in": "लॉगिन करें",

        "my_profile": "मेरी प्रोफ़ाइल",
        "save_profile": "प्रोफ़ाइल सहेजें",
        "view_profile": "प्रोफ़ाइल देखें",
        "profile_description":
            "अपनी व्यक्तिगत जानकारी देखें और अपडेट करें.",
        "email_cannot_change":
            "ईमेल बदला नहीं जा सकता.",
        "enter_phone":
            "फोन नंबर दर्ज करें",
        "enter_address":
            "अपना पता दर्ज करें",
        "back_to_dashboard":
            "डैशबोर्ड पर वापस जाएँ",

        "report_garbage": "कचरा रिपोर्ट करें",
        "report_garbage_help":
            "जानकारी और स्थान के साथ कचरे की रिपोर्ट करें.",
        "report_description":
            "अपने क्षेत्र में कचरे की रिपोर्ट करें और समुदाय को स्वच्छ रखने में मदद करें.",

        "waste_type": "कचरे का प्रकार",
        "select_waste_type":
            "कचरे का प्रकार चुनें",

        "dry_waste": "सूखा कचरा",
        "wet_waste": "गीला कचरा",
        "plastic_waste": "प्लास्टिक कचरा",
        "e_waste": "ई-कचरा",
        "construction": "निर्माण कचरा",
        "medical": "चिकित्सा कचरा",
        "mixed_waste": "मिश्रित कचरा",
        "other": "अन्य",

        "garbage_image":
            "कचरे की फोटो",
        "ai_detection_note":
            "अपलोड की गई फोटो से AI कचरे के प्रकार की पहचान करने में मदद कर सकता है.",
        "upload_clear_photo":
            "एक साफ फोटो अपलोड करें.",
        "maximum_size":
            "अधिकतम आकार: 5 MB.",

        "description": "विवरण",
        "description_placeholder":
            "कचरे की समस्या का वर्णन करें...",

        "location_locality":
            "स्थान / क्षेत्र",
        "location_example":
            "उदाहरण: पिंपरी, पुणे",

        "latitude": "अक्षांश",
        "longitude": "देशांतर",
        "optional": "वैकल्पिक",

        "anonymous_report":
            "इस रिपोर्ट को गुमनाम रूप से जमा करें",

        "submit_garbage_report":
            "कचरा रिपोर्ट जमा करें",

        "garbage_reports":
            "मेरी कचरा रिपोर्ट",

        "report_id": "रिपोर्ट ID",
        "location": "स्थान",
        "status": "स्थिति",
        "date": "दिनांक",

        "reported": "रिपोर्ट किया गया",
        "verified": "सत्यापित",
        "assigned": "सौंपा गया",
        "cleaning_in_progress":
            "सफाई जारी है",
        "cleaned": "साफ किया गया",
        "closed": "बंद",

        "not_provided": "उपलब्ध नहीं",
        "no_reports":
            "आपने अभी तक कोई रिपोर्ट जमा नहीं की है.",
        "first_report":
            "अपनी पहली रिपोर्ट जमा करें",

        "home_description":
            "कचरा रिपोर्टिंग और प्रबंधन के लिए समुदाय-आधारित प्लेटफ़ॉर्म.",
        "home_features":
            "कचरे की रिपोर्ट करें, स्थिति ट्रैक करें और स्वच्छ क्षेत्र बनाने में मदद करें.",

        "create_account":
            "खाता बनाएँ",
        "go_to_dashboard":
            "डैशबोर्ड पर जाएँ",
        "go_to_admin_dashboard":
            "प्रशासक डैशबोर्ड पर जाएँ",

        "admin_welcome":
            "स्वागत",
        "manage_reports":
            "उपयोगकर्ताओं द्वारा जमा की गई कचरा रिपोर्ट प्रबंधित करें.",

        "registered_users":
            "पंजीकृत उपयोगकर्ता",
        "total_reports":
            "कुल रिपोर्ट",
        "awaiting_action":
            "कार्रवाई की प्रतीक्षा",
        "cleaned_reports":
            "साफ की गई रिपोर्ट",

        "garbage_report_management":
            "कचरा रिपोर्ट प्रबंधन",

        "image": "फोटो",
        "reporter": "रिपोर्टकर्ता",
        "current_status":
            "वर्तमान स्थिति",
        "update_status":
            "स्थिति अपडेट करें",
        "view_image":
            "फोटो देखें",
        "no_image":
            "फोटो नहीं",
        "anonymous":
            "गुमनाम",
        "unknown_user":
            "अज्ञात उपयोगकर्ता",
        "new_report_status":
            "नई रिपोर्ट स्थिति",
        "save_status":
            "स्थिति सहेजें",

        "no_garbage_reports":
            "कोई कचरा रिपोर्ट नहीं",
        "submitted_reports_here":
            "जमा की गई कचरा रिपोर्ट यहाँ दिखाई देंगी.",

    }
}


# =========================================================
# TEMPLATE GLOBALS
# =========================================================

@app.context_processor
def inject_globals():

    current_language = session.get(
        "language",
        "mr"
    )

    db = get_db()

    current_user_name = ""
    current_user_role = "user"
    is_logged_in = False

    if "user_id" in session:

        user = db.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            """,
            (session["user_id"],)
        ).fetchone()

        if user:

            is_logged_in = True

            current_user_name = (
                user["full_name"]
                or ""
            )

            if user["is_admin"]:

                current_user_role = "admin"

    return {

        "current_language":
            current_language,

        "supported_languages":
            SUPPORTED_LANGUAGES,

        "t":
            TRANSLATIONS.get(
                current_language,
                TRANSLATIONS["mr"]
            ),

        "is_logged_in":
            is_logged_in,

        "current_user_name":
            current_user_name,

        "current_user_role":
            current_user_role,

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

    if language not in SUPPORTED_LANGUAGES:

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

        full_name = request.form.get(
            "full_name",
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

        if (
            not full_name
            or not email
            or not password
        ):

            flash(
                "Please fill all required fields.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if len(password) < 6:

            flash(
                "Password must be at least 6 characters.",
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
                full_name,
                email,
                password_hash
            )
            VALUES (?, ?, ?)
            """,
            (
                full_name,
                email,
                generate_password_hash(
                    password
                )
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

            if user["is_admin"]:

                return redirect(
                    url_for(
                        "admin_dashboard"
                    )
                )

            return redirect(
                url_for(
                    "user_dashboard"
                )
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
                url_for(
                    "admin_dashboard"
                )
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
def user_dashboard():

    db = get_db()

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

        full_name = request.form.get(
            "full_name",
            ""
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        address = request.form.get(
            "address",
            ""
        ).strip()

        if not full_name:

            flash(
                "Full name is required.",
                "danger"
            )

            return render_template(
                "profile.html",
                user=user
            )

        db.execute(
            """
            UPDATE users
            SET
                full_name = ?,
                phone = ?,
                address = ?
            WHERE id = ?
            """,
            (
                full_name,
                phone,
                address,
                session["user_id"]
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

        # =====================================================
        # DESCRIPTION
        # =====================================================

        description = request.form.get(
            "description",
            ""
        ).strip()

        # =====================================================
        # LOCATION
        # =====================================================

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

        # =====================================================
        # ANONYMOUS
        # =====================================================

        anonymous = (
            1
            if request.form.get("anonymous")
            else 0
        )

        # =====================================================
        # IMAGE
        # =====================================================

        image = request.files.get("image")

        if not image or not image.filename:

            flash(
                "Please upload a waste image.",
                "danger"
            )

            return render_template(
                "report.html"
            )

        # =====================================================
        # CHECK FILE EXTENSION
        # =====================================================

        extension = (
            image.filename
            .rsplit(".", 1)[-1]
            .lower()
        )

        if extension not in ALLOWED_EXTENSIONS:

            flash(
                "Invalid image format. "
                "Please upload JPG, JPEG, PNG or WEBP.",
                "danger"
            )

            return render_template(
                "report.html"
            )

        # =====================================================
        # SAVE IMAGE
        # =====================================================

        image_filename = secure_filename(
            f"{uuid4().hex}.{extension}"
        )

        image_path = (
            UPLOAD_FOLDER
            / image_filename
        )

        try:

            image.save(image_path)

        except Exception:

            flash(
                "Unable to save the uploaded image.",
                "danger"
            )

            return render_template(
                "report.html"
            )

        # =====================================================
        # AI CLASSIFICATION
        # =====================================================

        waste_type = ""

        if classifier is None:

            # AI is unavailable, for example on Render
            # where the heavy model is intentionally disabled.

            flash(
                "AI waste detection is currently unavailable. "
                "Please run the project locally where the AI model is enabled.",
                "danger"
            )

            try:
                image_path.unlink(
                    missing_ok=True
                )
            except Exception:
                pass

            return render_template(
                "report.html"
            )

        try:

            # Open image using PIL
            pil_image = Image.open(
                image_path
            ).convert("RGB")

            # Send image to Hugging Face classifier
            predictions = classifier(
                pil_image
            )

            if not predictions:

                raise ValueError(
                    "AI returned no predictions."
                )

            # Highest-confidence prediction
            top_prediction = predictions[0]

            top_label = str(
                top_prediction.get(
                    "label",
                    ""
                )
            ).strip().lower()

            # Convert model label into our project category
            waste_type = WASTE_MAP.get(
                top_label
            )

            if not waste_type:

                raise ValueError(
                    f"Unsupported AI label: {top_label}"
                )

        except Exception as error:

            print(
                "AI classification error:",
                error
            )

            flash(
                "The AI could not identify this waste image. "
                "Please upload a clearer waste photo.",
                "danger"
            )

            try:
                image_path.unlink(
                    missing_ok=True
                )
            except Exception:
                pass

            return render_template(
                "report.html"
            )

        # =====================================================
        # REPORT CODE
        # =====================================================

        report_code = (
            "SM-"
            + datetime.now().strftime(
                "%Y%m%d"
            )
            + "-"
            + uuid4().hex[:6].upper()
        )

        # =====================================================
        # SAVE REPORT
        # =====================================================

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
                anonymous
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
                anonymous
            )
        )

        db.commit()

        # =====================================================
        # SUCCESS
        # =====================================================

        flash(
            f"Report submitted successfully! "
            f"AI detected: {waste_type}. "
            f"Report ID: {report_code}",
            "success"
        )

        return redirect(
            url_for("user_dashboard")
        )

    # =========================================================
    # GET
    # =========================================================

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

    # =====================================================
    # REPORTS WITH USER INFORMATION
    # =====================================================

    reports = db.execute(
        """
        SELECT
            reports.*,
            users.full_name,
            users.email
        FROM reports
        LEFT JOIN users
            ON reports.user_id = users.id
        ORDER BY reports.id DESC
        """
    ).fetchall()

    # =====================================================
    # STATISTICS
    # =====================================================

    total_users = db.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE is_admin = 0
        """
    ).fetchone()[0]

    total_reports = db.execute(
        """
        SELECT COUNT(*)
        FROM reports
        """
    ).fetchone()[0]

    reported = db.execute(
        """
        SELECT COUNT(*)
        FROM reports
        WHERE status = 'Reported'
        """
    ).fetchone()[0]

    cleaned = db.execute(
        """
        SELECT COUNT(*)
        FROM reports
        WHERE status = 'Cleaned'
        """
    ).fetchone()[0]

    return render_template(
        "admin_dashboard.html",
        reports=reports,
        total_users=total_users,
        total_reports=total_reports,
        reported=reported,
        cleaned=cleaned
    )


# =========================================================
# UPDATE REPORT STATUS
# =========================================================

@app.route(
    "/admin/report/<int:report_id>/status",
    methods=["POST"]
)
@admin_required
def update_report_status(report_id):

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
            "Invalid report status.",
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
        "Report status updated successfully.",
        "success"
    )

    return redirect(
        url_for("admin_dashboard")
    )


# =========================================================
# OLD STATUS ROUTE
# =========================================================
#
# Kept for compatibility if an older template still points
# to /report/<id>/status.
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
            url_for("user_dashboard")
        )

    if (
        report["user_id"] != session["user_id"]
        and not (
            db.execute(
                """
                SELECT is_admin
                FROM users
                WHERE id = ?
                """,
                (session["user_id"],)
            ).fetchone()["is_admin"]
        )
    ):

        flash(
            "You do not have permission to view this report.",
            "danger"
        )

        return redirect(
            url_for("user_dashboard")
        )

    return redirect(
        url_for("user_dashboard")
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

    current_date = datetime.now().strftime(
        "%d %B %Y"
    )

    return render_template(
        "certificate.html",
        user=user,
        current_date=current_date
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
        "Dustbin location deleted successfully.",
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
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )
