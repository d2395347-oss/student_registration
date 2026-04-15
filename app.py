import os
import time
import hashlib
import random
from flask import Flask, render_template, request, jsonify
from twilio.rest import Client
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ================= ENV =================
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "student_db")

# ================= DATABASE =================
db_pool = pooling.MySQLConnectionPool(
    pool_name="student_pool",
    pool_size=5,
    host=DB_HOST,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME
)

def get_db():
    return db_pool.get_connection()

# ================= TWILIO =================
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")

client = Client(ACCOUNT_SID, AUTH_TOKEN)

# ================= OTP STORAGE =================
otp_store = {}
otp_verified = set()

OTP_EXPIRY = 300
OTP_MAX_ATTEMPTS = 5
otp_send_log = {}
OTP_RATE_WINDOW = 600
OTP_RATE_LIMIT = 3

# ================= HELPERS =================
def normalize_phone(phone):
    phone = phone.strip()
    if not phone.startswith("+91"):
        phone = "+91" + phone
    return phone

def validate_phone(phone):
    return phone.replace("+91", "").isdigit() and len(phone.replace("+91", "")) == 10

def validate_aadhaar(aadhaar):
    return aadhaar.isdigit() and len(aadhaar) == 12

def hash_aadhaar(aadhaar):
    return hashlib.sha256(aadhaar.encode()).hexdigest()

def is_rate_limited(phone):
    now = time.time()
    history = otp_send_log.get(phone, [])
    history = [t for t in history if now - t < OTP_RATE_WINDOW]
    otp_send_log[phone] = history
    return len(history) >= OTP_RATE_LIMIT

# ================= ROUTES =================
@app.route('/')
def home():
    return render_template("form.html")

@app.route('/send_otp', methods=['POST'])
def send_otp():
    phone = normalize_phone(request.form.get('phone', ''))

    if not validate_phone(phone):
        return jsonify({"status": "error", "message": "Invalid phone number"})

    if is_rate_limited(phone):
        return jsonify({"status": "error", "message": "Too many OTP requests"})

    otp = str(random.randint(100000, 999999))
    otp_store[phone] = {"otp": otp, "time": time.time(), "attempts": 0}
    otp_send_log.setdefault(phone, []).append(time.time())

    try:
        client.messages.create(
            body=f"Your OTP is {otp}. Valid for 5 minutes.",
            from_=TWILIO_NUMBER,
            to=phone
        )
        return jsonify({"status": "success", "message": "OTP sent"})
    except Exception as e:
        print("Twilio error:", e)
        return jsonify({"status": "error", "message": "Failed to send OTP"})

@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    phone = normalize_phone(request.form.get('phone', ''))
    otp = request.form.get('otp', '').strip()

    if phone not in otp_store:
        return jsonify({"status": "error", "message": "OTP not found"})

    data = otp_store[phone]

    if time.time() - data["time"] > OTP_EXPIRY:
        del otp_store[phone]
        return jsonify({"status": "error", "message": "OTP expired"})

    if data["attempts"] >= OTP_MAX_ATTEMPTS:
        del otp_store[phone]
        return jsonify({"status": "error", "message": "Too many attempts"})

    if otp == data["otp"]:
        otp_verified.add(phone)
        del otp_store[phone]
        return jsonify({"status": "success", "message": "Verified"})
    else:
        otp_store[phone]["attempts"] += 1
        return jsonify({"status": "error", "message": "Wrong OTP"})

@app.route('/submit', methods=['POST'])
def submit():
    name = request.form.get('name', '').strip()
    father = request.form.get('father_name', '').strip()
    caste = request.form.get('caste', '').strip()
    phone = normalize_phone(request.form.get('phone', ''))
    aadhaar = request.form.get('aadhaar', '').strip()

    if not otp_verified.__contains__(phone):
        return jsonify({"status": "error", "message": "Verify OTP first"}), 403

    aadhaar_hash = hash_aadhaar(aadhaar)

    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO students (name, father_name, caste, phone, aadhaar_hash)
            VALUES (%s, %s, %s, %s, %s)
        """, (name, father, caste, phone, aadhaar_hash))

        conn.commit()
        otp_verified.discard(phone)

        return jsonify({"status": "success", "message": "Registered"})

    except mysql.connector.IntegrityError:
        return jsonify({"status": "error", "message": "Duplicate entry"}), 409

    finally:
        cursor.close()
        conn.close()

@app.route('/students')
def students():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, father_name, caste, phone FROM students")
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("students.html", students=data)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)