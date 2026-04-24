import os
import smtplib
from datetime import date
import time
import hashlib
import random
import re
from urllib.parse import urlparse
from functools import wraps
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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
print("DB_URL        :", "SET" if os.getenv("DB_URL") else "MISSING")
print("Twilio SID    :", "SET" if os.getenv("TWILIO_ACCOUNT_SID") else "MISSING")
print("Twilio TOKEN  :", "SET" if os.getenv("TWILIO_AUTH_TOKEN") else "MISSING")
print("Twilio SMS NUM:", os.getenv("TWILIO_NUMBER") or "MISSING")
print("Twilio WA NUM :", os.getenv("TWILIO_WHATSAPP_NUMBER") or "MISSING")
print("Gmail User    :", os.getenv("GMAIL_USER") or "MISSING")
print("Gmail Pass    :", "SET" if os.getenv("GMAIL_PASSWORD") else "MISSING")
print("School Name   :", os.getenv("SCHOOL_NAME", "Our School"))
print("=" * 50)

# ================= CONFIG =================
ADMIN_USERNAME        = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD        = os.getenv("ADMIN_PASSWORD", "school@123")
SCHOOL_NAME           = os.getenv("SCHOOL_NAME", "Our School")
SCHOOL_EMAIL          = os.getenv("SCHOOL_EMAIL", "")
GMAIL_USER            = os.getenv("GMAIL_USER", "")
GMAIL_PASSWORD        = os.getenv("GMAIL_PASSWORD", "")
TWILIO_NUMBER         = os.getenv("TWILIO_NUMBER", "")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "")  # e.g. whatsapp:+14155238886

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

_url = urlparse(DB_URL)
db_pool = pooling.MySQLConnectionPool(
    pool_name="student_pool",
    pool_size=5,
    host=_url.hostname,
    user=_url.username,
    password=_url.password,
    database=_url.path.lstrip("/"),
    port=_url.port or 3306
)

def get_db():
    return db_pool.get_connection()

# ================= TWILIO =================
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
twilio_client = Client(ACCOUNT_SID, AUTH_TOKEN)

# ================= OTP =================
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
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        return filename
    return None

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

# ================================================================
# ================= NOTIFICATION FUNCTIONS =======================
# ================================================================

# -------- SMS --------
def send_sms(to_phone, message):
    """Send plain SMS via Twilio."""
    if not TWILIO_NUMBER:
        print("[SMS] SKIPPED - TWILIO_NUMBER not set")
        return
    try:
        msg = twilio_client.messages.create(
            body=message,
            from_=TWILIO_NUMBER,
            to=to_phone
        )
        print(f"[SMS] Sent to {to_phone} | SID: {msg.sid}")
    except Exception as e:
        print(f"[SMS] ERROR to {to_phone}: {e}")


# -------- WHATSAPP --------
def send_whatsapp(to_phone, message):
    """Send WhatsApp message via Twilio WhatsApp sandbox."""
    if not TWILIO_WHATSAPP_NUMBER:
        print("[WhatsApp] SKIPPED - TWILIO_WHATSAPP_NUMBER not set")
        return
    try:
        # Format: whatsapp:+91XXXXXXXXXX
        wa_to = f"whatsapp:{to_phone}"
        msg = twilio_client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=wa_to
        )
        print(f"[WhatsApp] Sent to {to_phone} | SID: {msg.sid}")
    except Exception as e:
        print(f"[WhatsApp] ERROR to {to_phone}: {e}")


# -------- EMAIL --------
def send_email(to_email, subject, html_body):
    """Send HTML email via Gmail SMTP."""
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print("[Email] SKIPPED - Gmail credentials not set")
        return
    if not to_email or "@" not in to_email:
        print(f"[Email] SKIPPED - invalid email: {to_email}")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{SCHOOL_NAME} <{GMAIL_USER}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, to_email, msg.as_string())
        print(f"[Email] Sent to {to_email}")
    except Exception as e:
        print(f"[Email] ERROR to {to_email}: {e}")


# -------- NOTIFY ALL CHANNELS --------
def notify_registration(name, phone, email, class_applied):
    """Notify parent when registration is submitted."""

    sms_msg = (
        f"Dear Parent,\n"
        f"Thank you! {name}'s application for {class_applied} at {SCHOOL_NAME} "
        f"has been received successfully.\n"
        f"You will be notified once the application is reviewed.\n"
        f"- {SCHOOL_NAME}"
    )

    wa_msg = (
        f"🏫 *{SCHOOL_NAME}*\n\n"
        f"Dear Parent,\n\n"
        f"✅ Thank you for registering!\n\n"
        f"*Student Name:* {name}\n"
        f"*Class Applied:* {class_applied}\n\n"
        f"Your application has been received and is under review. "
        f"We will notify you once a decision is made.\n\n"
        f"_- School Administration_"
    )

    email_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;border:1px solid #e0e0e0;border-radius:12px;overflow:hidden;">
        <div style="background:#1a3c6e;padding:24px;text-align:center;">
            <h1 style="color:white;margin:0;font-size:22px;">🏫 {SCHOOL_NAME}</h1>
            <p style="color:#a0bce0;margin:6px 0 0;">Admission Portal</p>
        </div>
        <div style="padding:32px;">
            <h2 style="color:#1a3c6e;">Registration Received ✅</h2>
            <p style="color:#555;line-height:1.7;">Dear Parent,</p>
            <p style="color:#555;line-height:1.7;">
                Thank you for submitting the admission application for <strong>{name}</strong> 
                for class <strong>{class_applied}</strong>.
            </p>
            <div style="background:#f0f4f8;border-radius:8px;padding:16px;margin:20px 0;">
                <table style="width:100%;border-collapse:collapse;">
                    <tr><td style="padding:6px 0;color:#888;font-size:13px;">Student Name</td><td style="padding:6px 0;font-weight:600;">{name}</td></tr>
                    <tr><td style="padding:6px 0;color:#888;font-size:13px;">Class Applied</td><td style="padding:6px 0;font-weight:600;">{class_applied}</td></tr>
                    <tr><td style="padding:6px 0;color:#888;font-size:13px;">Status</td><td style="padding:6px 0;"><span style="background:#fff3e0;color:#e67e22;padding:3px 10px;border-radius:20px;font-size:13px;font-weight:600;">PENDING REVIEW</span></td></tr>
                </table>
            </div>
            <p style="color:#555;line-height:1.7;">
                We will notify you via SMS, WhatsApp, and email once your application is reviewed.
            </p>
            <p style="color:#999;font-size:13px;margin-top:24px;">- {SCHOOL_NAME} Administration</p>
        </div>
        <div style="background:#f8f9fa;padding:16px;text-align:center;border-top:1px solid #e0e0e0;">
            <p style="color:#aaa;font-size:12px;margin:0;">This is an automated message. Please do not reply.</p>
        </div>
    </div>
    """

    send_sms(phone, sms_msg)
    send_whatsapp(phone, wa_msg)
    send_email(email, f"Registration Received - {SCHOOL_NAME}", email_html)


def notify_accepted(name, phone, email, class_applied, fees_date, fees_time):
    """Notify parent when application is accepted."""

    sms_msg = (
        f"Dear Parent,\n\n"
        f"Congratulations! {name}'s admission for {class_applied} at {SCHOOL_NAME} "
        f"has been ACCEPTED.\n\n"
        f"Please visit on {fees_date} at {fees_time} for fees submission.\n"
        f"Bring all original documents.\n"
        f"- {SCHOOL_NAME}"
    )

    wa_msg = (
        f"🏫 *{SCHOOL_NAME}*\n\n"
        f"Dear Parent,\n\n"
        f"🎉 *Congratulations!*\n\n"
        f"*{name}'s* admission application for *{class_applied}* has been *ACCEPTED*!\n\n"
        f"📅 *Fees Submission Date:* {fees_date}\n"
        f"🕐 *Reporting Time:* {fees_time}\n\n"
        f"📋 *Please bring:*\n"
        f"• All original documents\n"
        f"• Birth certificate\n"
        f"• Previous marksheet\n"
        f"• Passport size photos\n\n"
        f"We look forward to welcoming {name} to our school!\n\n"
        f"_- School Administration_"
    )

    email_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;border:1px solid #e0e0e0;border-radius:12px;overflow:hidden;">
        <div style="background:#1a9e5c;padding:24px;text-align:center;">
            <h1 style="color:white;margin:0;font-size:22px;">🎉 Admission Accepted!</h1>
            <p style="color:#a0e0c0;margin:6px 0 0;">{SCHOOL_NAME}</p>
        </div>
        <div style="padding:32px;">
            <h2 style="color:#1a9e5c;">Congratulations! ✅</h2>
            <p style="color:#555;line-height:1.7;">Dear Parent,</p>
            <p style="color:#555;line-height:1.7;">
                We are pleased to inform you that <strong>{name}'s</strong> admission application 
                for class <strong>{class_applied}</strong> has been <strong>ACCEPTED</strong>.
            </p>
            <div style="background:#e8f5e9;border:1.5px solid #a5d6a7;border-radius:8px;padding:20px;margin:20px 0;text-align:center;">
                <p style="margin:0;font-size:13px;color:#555;">Please visit the school for fees submission</p>
                <p style="margin:8px 0 0;font-size:22px;font-weight:700;color:#1a9e5c;">📅 {fees_date}</p>
                <p style="margin:4px 0 0;font-size:16px;color:#555;">🕐 {fees_time}</p>
            </div>
            <div style="background:#f0f4f8;border-radius:8px;padding:16px;margin:20px 0;">
                <p style="margin:0 0 10px;font-weight:600;color:#1a3c6e;">📋 Documents to bring:</p>
                <ul style="margin:0;padding-left:20px;color:#555;line-height:2;">
                    <li>All original documents</li>
                    <li>Birth certificate</li>
                    <li>Previous year marksheet</li>
                    <li>Category certificate (if applicable)</li>
                    <li>4 passport size photographs</li>
                </ul>
            </div>
            <p style="color:#555;line-height:1.7;">
                We look forward to welcoming <strong>{name}</strong> to the {SCHOOL_NAME} family!
            </p>
            <p style="color:#999;font-size:13px;margin-top:24px;">- {SCHOOL_NAME} Administration</p>
        </div>
        <div style="background:#f8f9fa;padding:16px;text-align:center;border-top:1px solid #e0e0e0;">
            <p style="color:#aaa;font-size:12px;margin:0;">This is an automated message. Please do not reply.</p>
        </div>
    </div>
    """

    send_sms(phone, sms_msg)
    send_whatsapp(phone, wa_msg)
    send_email(email, f"Admission Accepted - {name} | {SCHOOL_NAME}", email_html)


def notify_rejected(name, phone, email, class_applied, reason=""):
    """Notify parent when application is rejected."""

    sms_msg = (
        f"Dear Parent,\n\n"
        f"We regret to inform you that {name}'s admission application "
        f"for {class_applied} at {SCHOOL_NAME} has not been accepted at this time.\n"
        f"For details, please contact the school office.\n"
        f"- {SCHOOL_NAME}"
    )

    wa_msg = (
        f"🏫 *{SCHOOL_NAME}*\n\n"
        f"Dear Parent,\n\n"
        f"We regret to inform you that *{name}'s* admission application "
        f"for *{class_applied}* has not been accepted at this time.\n\n"
        f"{'*Reason:* ' + reason + chr(10) + chr(10) if reason else ''}"
        f"For more information, please contact the school office.\n\n"
        f"_- School Administration_"
    )

    email_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;border:1px solid #e0e0e0;border-radius:12px;overflow:hidden;">
        <div style="background:#d63031;padding:24px;text-align:center;">
            <h1 style="color:white;margin:0;font-size:22px;">Application Status Update</h1>
            <p style="color:#ffa0a0;margin:6px 0 0;">{SCHOOL_NAME}</p>
        </div>
        <div style="padding:32px;">
            <h2 style="color:#d63031;">Application Not Accepted</h2>
            <p style="color:#555;line-height:1.7;">Dear Parent,</p>
            <p style="color:#555;line-height:1.7;">
                We regret to inform you that <strong>{name}'s</strong> admission application 
                for class <strong>{class_applied}</strong> has not been accepted at this time.
            </p>
            {'<div style="background:#fdecea;border-radius:8px;padding:16px;margin:16px 0;"><strong>Reason:</strong> ' + reason + '</div>' if reason else ''}
            <p style="color:#555;line-height:1.7;">
                For more information or to inquire about future admission cycles, 
                please contact our school office.
            </p>
            <p style="color:#999;font-size:13px;margin-top:24px;">- {SCHOOL_NAME} Administration</p>
        </div>
        <div style="background:#f8f9fa;padding:16px;text-align:center;border-top:1px solid #e0e0e0;">
            <p style="color:#aaa;font-size:12px;margin:0;">This is an automated message. Please do not reply.</p>
        </div>
    </div>
    """

    send_sms(phone, sms_msg)
    send_whatsapp(phone, wa_msg)
    send_email(email, f"Application Update - {name} | {SCHOOL_NAME}", email_html)


# ================================================================
# ======================== ROUTES ================================
# ================================================================

@app.route("/")
def home():
    return render_template("form.html")

# -------- SEND OTP --------
@app.route("/send_otp", methods=["POST"])
def send_otp():
    raw_phone = request.form.get("phone", "")
    phone = normalize_phone(raw_phone)

    print(f"\n[OTP] Raw: '{raw_phone}' → Normalized: '{phone}'")

    if not valid_mobile(phone):
        return jsonify({"status": "error", "message": "Invalid mobile number format"})

    otp = str(random.randint(100000, 999999))
    otp_store[phone] = {"otp": otp, "time": time.time()}
    print(f"[OTP] Generated: {otp} for {phone}")

    try:
        msg = twilio_client.messages.create(
            body=f"Your {SCHOOL_NAME} registration OTP is {otp}. Valid for 5 minutes.",
            from_=TWILIO_NUMBER,
            to=phone
        )
        print(f"[OTP] SUCCESS - SID: {msg.sid}")
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"[OTP] ERROR: {e}")
        return jsonify({"status": "error", "message": str(e)})

# -------- VERIFY OTP --------
@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    raw_phone = request.form.get("phone", "")
    phone = normalize_phone(raw_phone)
    otp   = request.form.get("otp", "").strip()

    data = otp_store.get(phone)
    if not data:
        return jsonify({"status": "error", "message": "No OTP found. Please send OTP first."})
    if time.time() - data["time"] > OTP_EXPIRY:
        otp_store.pop(phone, None)
        return jsonify({"status": "error", "message": "OTP expired. Please resend."})
    if otp == data["otp"]:
        otp_verified.add(phone)
        otp_store.pop(phone, None)
        return jsonify({"status": "success"})
    else:
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
    email                = request.form.get("email", "").strip().lower()

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
                phone_no, aadhaar_no, pan_no, email,
                special_child, extra_activity, achievement,
                hobbies, sports,
                special_file, extra_file, achievement_file,
                status
            ) VALUES (
                %s,%s,%s,%s, %s,%s,%s, %s,%s,%s,
                %s,%s,%s,%s, %s,%s,%s, %s,%s, %s,%s,%s, %s
            )
        """, (
            name, father_name, date_of_birth, address,
            father_occupation, academic_year, previous_institution,
            class_applied, category, gender,
            phone, aadhaar_hash, pan_no, email,
            special_child, extra_activity, achievement,
            hobbies, sports,
            special_file, extra_file, achievement_file,
            "pending"
        ))
        conn.commit()
        otp_verified.discard(phone)
        print(f"[SUBMIT] SUCCESS - {name}")

        # Send registration confirmation notifications
        notify_registration(name, phone, email, class_applied)

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

# -------- PUBLIC STATUS CHECK --------
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
        FROM students WHERE phone_no=%s ORDER BY id DESC LIMIT 1
    """, (phone,))
    student = cursor.fetchone()
    cursor.close()
    conn.close()
    return jsonify({"found": True, "student": student} if student else {"found": False})

# -------- ADMIN LOGIN --------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if (request.form.get("username") == ADMIN_USERNAME and
                request.form.get("password") == ADMIN_PASSWORD):
            session["admin_logged_in"] = True
            return redirect(url_for("admin_panel"))
        return render_template("admin_login.html", error="Invalid username or password")
    return render_template("admin_login.html", error=None)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))

# -------- ADMIN PANEL --------
@app.route("/admin")
@admin_required
def admin_panel():
    conn   = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, name, father_name, class_applied, category, gender, phone_no, email, status
        FROM students ORDER BY id DESC
    """)
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("admin.html", students=data)

# -------- APPROVE --------
@app.route("/approve/<int:student_id>", methods=["GET", "POST"])
@admin_required
def approve(student_id):
    if request.method == "GET":
        conn   = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, class_applied, phone_no, email FROM students WHERE id=%s", (student_id,))
        student = cursor.fetchone()
        cursor.close()
        conn.close()
        if not student:
            return "Student not found", 404
        return render_template("approve_confirm.html", student=student, today=date.today().isoformat())

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

    phone = student["phone_no"]
    name  = student["name"]
    email = student.get("email", "")

    if cls["filled_seats"] < cls["total_seats"]:
        cursor.execute("UPDATE students SET status='accepted' WHERE id=%s", (student_id,))
        cursor.execute("UPDATE classes SET filled_seats=filled_seats+1 WHERE class_name=%s", (class_name,))
        conn.commit()
        # Send acceptance notifications (SMS + WhatsApp + Email)
        notify_accepted(name, phone, email, class_name, fees_date, fees_time)
    else:
        cursor.execute("UPDATE students SET status='rejected' WHERE id=%s", (student_id,))
        conn.commit()
        # Seats full - notify rejection
        notify_rejected(name, phone, email, class_name, reason="All seats are filled for this class.")

    cursor.close()
    conn.close()
    return redirect(url_for("admin_panel"))

# -------- REJECT --------
@app.route("/reject/<int:student_id>")
@admin_required
def reject(student_id):
    conn   = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT name, class_applied, phone_no, email FROM students WHERE id=%s", (student_id,))
    student = cursor.fetchone()

    if student:
        cursor.execute("UPDATE students SET status='rejected' WHERE id=%s", (student_id,))
        conn.commit()
        notify_rejected(
            student["name"],
            student["phone_no"],
            student.get("email", ""),
            student["class_applied"]
        )

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
