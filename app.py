import os
import time
import hashlib
import random
import urllib.parse as urlparse

from flask import Flask, render_template, request, jsonify
from twilio.rest import Client
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ================= DATABASE (USE DB_URL FROM RAILWAY) =================
db_url = os.getenv("DB_URL")

if not db_url:
    raise Exception("❌ DB_URL not found in environment variables")

url = urlparse.urlparse(db_url)

db_pool = pooling.MySQLConnectionPool(
    pool_name="student_pool",
    pool_size=5,
    host=url.hostname,
    user=url.username,
    password=url.password,
    database=url.path[1:],  # remove leading '/'
    port=url.port
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
OTP_RATE_LIMIT = 3
OTP_RATE_WINDOW = 600
otp_send_log = {}


# ================= HELPERS =================
def normalize_phone(phone):
    phone = phone.strip()
    if not phone.startswith("+91"):
        phone = "+91" + phone
    return phone

def validate_phone(phone):
    digits = phone.replace("+91", "")
    return digits.isdigit() and len(digits) == 10

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
        return jsonify({"status": "error", "message": "Too many OTP requests. Try later."})

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
        return jsonify({"status": "success", "message": "Phone verified"})
    else:
        otp_store[phone]["attempts"] += 1
        return jsonify({"status": "error", "message": "Invalid OTP"})


@app.route('/submit', methods=['POST'])
def submit():
    name = request.form.get('name', '').strip()
    father = request.form.get('father_name', '').strip()
    caste = request.form.get('caste', '').strip()
    phone = normalize_phone(request.form.get('phone', ''))
    aadhaar = request.form.get('aadhaar', '').strip()

    # Validation
    if not name:
        return jsonify({"status": "error", "message": "Name required"}), 400

    if not validate_phone(phone):
        return jsonify({"status": "error", "message": "Invalid phone"}), 400

    if not validate_aadhaar(aadhaar):
        return jsonify({"status": "error", "message": "Aadhaar must be 12 digits"}), 400

    if phone not in otp_verified:
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

        return jsonify({"status": "success", "message": "Registration successful"})

    except mysql.connector.IntegrityError:
        return jsonify({"status": "error", "message": "Already registered"}), 409

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


# ================= RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)