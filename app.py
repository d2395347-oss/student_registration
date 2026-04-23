import os
from datetime import date
import time
import hashlib
import random
import re
from urllib.parse import urlparse
from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from twilio.rest import Client
import mysql.connector
from mysql.connector import pooling
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "school_secret_key_2024")

# ================= STARTUP CHECK =================
print("=" * 50)
print("Flask starting...")
print("DB_URL      :", "SET" if os.getenv("DB_URL") else "MISSING - check .env")
print("Twilio SID  :", "SET" if os.getenv("TWILIO_ACCOUNT_SID") else "MISSING - check .env")
print("Twilio TOKEN:", "SET" if os.getenv("TWILIO_AUTH_TOKEN") else "MISSING - check .env")
print("Twilio NUM  :", os.getenv("TWILIO_NUMBER") or "MISSING - check .env")
print("=" * 50)

# ================= ADMIN CREDENTIALS =================
# Change these in your .env file!
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "school@123")

# ================= FILE UPLOAD =================
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ================= DATABASE =================
DB_URL = os.getenv("DB_URL")
if not DB_URL:
    raise Exception("DB_URL not found in .env file")

url = urlparse(DB_URL)

db_pool = pooling.MySQLConnectionPool(
    pool_name="student_pool",
    pool_size=5,
    host=url.hostname,
    user=url.username,
    password=url.password,
    database=url.path.lstrip("/"),
    port=url.port or 3306
)

def get_db():
    return db_pool.get_connection()

# ================= TWILIO =================
ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")

twilio_client = Client(ACCOUNT_SID, AUTH_TOKEN)

# ================= OTP STORE =================
otp_store    = {}
otp_verified = set()
OTP_EXPIRY   = 300

# ================= HELPERS =================
def normalize_phone(phone):
    phone = phone.strip() if phone else ""
    phone = re.sub(r"^\+91", "", phone).strip()
    return "+91" + phone

def hash_aadhaar(aadhaar):
    return hashlib.sha256(aadhaar.encode()).hexdigest()

def valid_aadhaar(aadhaar):
    return bool(re.fullmatch(r"\d{12}", aadhaar))

def valid_pan(pan):
    return bool(re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan.upper()))

def valid_mobile(phone):
    return bool(re.fullmatch(r"\+91\d{10}", phone))

def save_file(file):
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(path)
        return filename
    return None

# ================= ADMIN LOGIN REQUIRED =================
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

# ================= ROUTES =================
@app.route("/")
def home():
    return render_template("form.html")

# -------- SEND OTP --------
@app.route("/send_otp", methods=["POST"])
def send_otp():
    raw_phone = request.form.get("phone", "")
    phone = normalize_phone(raw_phone)

    print(f"\n[OTP] Raw input  : '{raw_phone}'")
    print(f"[OTP] Normalized : '{phone}'")
    print(f"[OTP] From number: '{TWILIO_NUMBER}'")

    if not valid_mobile(phone):
        print(f"[OTP] FAILED - invalid mobile format")
        return jsonify({"status": "error", "message": "Invalid mobile number format"})

    otp = str(random.randint(100000, 999999))
    otp_store[phone] = {"otp": otp, "time": time.time()}
    print(f"[OTP] Generated OTP: {otp} for {phone}")

    try:
        msg = twilio_client.messages.create(
            body=f"Your school registration OTP is {otp}. Valid for 5 minutes.",
            from_=TWILIO_NUMBER,
            to=phone
        )
        print(f"[OTP] SUCCESS - Twilio SID: {msg.sid}")
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"[OTP] TWILIO ERROR: {e}")
        return jsonify({"status": "error", "message": str(e)})

# -------- VERIFY OTP --------
@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    raw_phone = request.form.get("phone", "")
    phone = normalize_phone(raw_phone)
    otp   = request.form.get("otp", "").strip()

    print(f"\n[VERIFY] Phone : {phone}, OTP: {otp}")

    data = otp_store.get(phone)

    if not data:
        return jsonify({"status": "error", "message": "No OTP found. Please send OTP first."})

    if time.time() - data["time"] > OTP_EXPIRY:
        otp_store.pop(phone, None)
        return jsonify({"status": "error", "message": "OTP expired. Please resend."})

    if otp == data["otp"]:
        otp_verified.add(phone)
        otp_store.pop(phone, None)
        print(f"[VERIFY] SUCCESS for {phone}")
        return jsonify({"status": "success"})
    else:
        print(f"[VERIFY] FAILED - expected {data['otp']}, got {otp}")
        return jsonify({"status": "error", "message": "Incorrect OTP. Please try again."})

# -------- SUBMIT FORM --------
@app.route("/submit", methods=["POST"])
def submit():
    raw_phone = request.form.get("mobile", "")
    phone = normalize_phone(raw_phone)

    if phone not in otp_verified:
        return "Mobile not verified. Please verify OTP first.", 400

    name                 = request.form.get("name", "").strip()
    father_name          = request.form.get("father_name", "").strip()
    date_of_birth        = request.form.get("date_of_birth", "").strip()
    address              = request.form.get("address", "").strip()
    father_occupation    = request.form.get("father_occupation", "").strip()
    academic_year        = request.form.get("academic_year", "").strip()
    previous_institution = request.form.get("previous_institution_name", "").strip()
    class_applied        = request.form.get("class_applied", "").strip()
    category             = request.form.get("category", "").strip()
    gender               = request.form.get("gender", "").strip()
    special_child        = request.form.get("special_child", "no")
    extra_activity       = request.form.get("extra_activity", "no")
    achievement          = request.form.get("achievement", "no")
    hobbies              = request.form.get("hobbies", "").strip()
    sports               = request.form.get("sports", "").strip()
    aadhaar              = request.form.get("aadhaar", "").strip()
    pan_no               = request.form.get("pan_no", "").strip().upper()

    errors = []
    if not name:                   errors.append("Name is required")
    if not father_name:            errors.append("Father name is required")
    if not date_of_birth:          errors.append("Date of birth is required")
    if not class_applied:          errors.append("Class is required")
    if not category:               errors.append("Category is required")
    if not valid_aadhaar(aadhaar): errors.append("Invalid Aadhaar (must be 12 digits)")
    if not valid_pan(pan_no):      errors.append("Invalid PAN format (e.g. ABCDE1234F)")

    if errors:
        return "<br>".join(errors), 400

    aadhaar_hash     = hash_aadhaar(aadhaar)
    special_file     = save_file(request.files.get("special_file"))
    extra_file       = save_file(request.files.get("extra_file"))
    achievement_file = save_file(request.files.get("achievement_file"))

    conn   = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO students (
                name, father_name, date_of_birth, address,
                father_occupation, academic_year, previous_institution_name,
                class_applied, category, gender,
                phone_no, aadhaar_no, pan_no,
                special_child, extra_activity, achievement,
                hobbies, sports,
                special_file, extra_file, achievement_file,
                status
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s
            )
        """, (
            name, father_name, date_of_birth, address,
            father_occupation, academic_year, previous_institution,
            class_applied, category, gender,
            phone, aadhaar_hash, pan_no,
            special_child, extra_activity, achievement,
            hobbies, sports,
            special_file, extra_file, achievement_file,
            "pending"
        ))
        conn.commit()
        otp_verified.discard(phone)
        print(f"[SUBMIT] SUCCESS - Student '{name}' registered")

    except Exception as e:
        conn.rollback()
        print(f"[SUBMIT] DB ERROR: {e}")
        return f"Registration failed: {e}", 500

    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("success"))

# -------- SUCCESS PAGE --------
@app.route("/success")
def success():
    return render_template("success.html")

# -------- PUBLIC: CHECK STATUS BY PHONE --------
@app.route("/students")
def students():
    return render_template("students.html")

@app.route("/check_status", methods=["POST"])
def check_status():
    raw_phone = request.form.get("phone", "")
    phone = normalize_phone(raw_phone)

    conn   = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT name, father_name, class_applied, category, gender, phone_no, status
        FROM students WHERE phone_no = %s ORDER BY id DESC LIMIT 1
    """, (phone,))
    student = cursor.fetchone()
    cursor.close()
    conn.close()

    if student:
        return jsonify({"found": True, "student": student})
    else:
        return jsonify({"found": False})

# -------- ADMIN LOGIN --------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_panel"))
        else:
            return render_template("admin_login.html", error="Invalid username or password")

    return render_template("admin_login.html", error=None)

# -------- ADMIN LOGOUT --------
@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))

# -------- ADMIN PANEL (PROTECTED) --------
@app.route("/admin")
@admin_required
def admin_panel():
    conn   = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, name, father_name, class_applied, category, gender, phone_no, status
        FROM students ORDER BY id DESC
    """)
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("admin.html", students=data)

# -------- APPROVE (ADMIN ONLY) --------
@app.route("/approve/<int:student_id>", methods=["GET", "POST"])
@admin_required
def approve(student_id):
    # GET: show date picker confirmation page
    if request.method == "GET":
        conn   = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, class_applied, phone_no FROM students WHERE id=%s", (student_id,))
        student = cursor.fetchone()
        cursor.close()
        conn.close()
        if not student:
            return "Student not found", 404
        return render_template("approve_confirm.html", student=student, today=date.today().isoformat())

    # POST: process approval with fees date
    fees_date = request.form.get("fees_date", "").strip()
    fees_time = request.form.get("fees_time", "9:00 AM").strip()

    conn   = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM students WHERE id=%s", (student_id,))
    student = cursor.fetchone()

    if not student:
        cursor.close()
        conn.close()
        return "Student not found", 404

    class_name = student["class_applied"]
    cursor.execute("SELECT * FROM classes WHERE class_name=%s", (class_name,))
    cls = cursor.fetchone()

    if not cls:
        cursor.close()
        conn.close()
        return f"Class '{class_name}' not found in system.", 400

    if cls["filled_seats"] < cls["total_seats"]:
        cursor.execute("UPDATE students SET status='accepted' WHERE id=%s", (student_id,))
        cursor.execute("UPDATE classes SET filled_seats=filled_seats+1 WHERE class_name=%s", (class_name,))
        conn.commit()

        # Send acceptance SMS with fees date
        phone    = student["phone_no"]
        name     = student["name"]
        sms_body = (
            f"Dear Parent,\n\n"
            f"Congratulations! {name}'s admission application for {class_name} has been ACCEPTED.\n\n"
            f"Please visit the school on {fees_date} at {fees_time} for fees submission.\n\n"
            f"Kindly bring all original documents.\n"
            f"- School Administration"
        )
        try:
            twilio_client.messages.create(body=sms_body, from_=TWILIO_NUMBER, to=phone)
            print(f"[SMS] Acceptance SMS sent to {phone}")
        except Exception as e:
            print(f"[SMS] ERROR: {e}")

    else:
        cursor.execute("UPDATE students SET status='rejected' WHERE id=%s", (student_id,))
        conn.commit()

        # Notify seats full
        phone    = student["phone_no"]
        name     = student["name"]
        sms_body = (
            f"Dear Parent,\n\n"
            f"We regret that {name}'s application for {class_name} "
            f"could not be accepted as all seats are full.\n\n"
            f"- School Administration"
        )
        try:
            twilio_client.messages.create(body=sms_body, from_=TWILIO_NUMBER, to=phone)
            print(f"[SMS] Seats-full rejection SMS sent to {phone}")
        except Exception as e:
            print(f"[SMS] ERROR: {e}")

    cursor.close()
    conn.close()
    return redirect(url_for("admin_panel"))

# -------- REJECT (ADMIN ONLY) --------
@app.route("/reject/<int:student_id>")
@admin_required
def reject(student_id):
    conn   = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT name, class_applied, phone_no FROM students WHERE id=%s", (student_id,))
    student = cursor.fetchone()

    if student:
        cursor.execute("UPDATE students SET status='rejected' WHERE id=%s", (student_id,))
        conn.commit()

        # Send rejection SMS
        phone    = student["phone_no"]
        name     = student["name"]
        sms_body = (
            f"Dear Parent,\n\n"
            f"We regret to inform you that {name}'s admission application "
            f"has not been accepted at this time.\n\n"
            f"For more information, please contact the school office.\n"
            f"- School Administration"
        )
        try:
            twilio_client.messages.create(body=sms_body, from_=TWILIO_NUMBER, to=phone)
            print(f"[SMS] Rejection SMS sent to {phone}")
        except Exception as e:
            print(f"[SMS] ERROR: {e}")

    cursor.close()
    conn.close()
    return redirect(url_for("admin_panel"))

# -------- ERROR HANDLERS --------
@app.errorhandler(405)
def method_not_allowed(e):
    return redirect(url_for("home"))

@app.errorhandler(404)
def not_found(e):
    return redirect(url_for("home"))

# ================= RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)