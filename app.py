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

# ================= DATABASE =================
db_url = os.getenv("DB_URL")

if not db_url:
    raise Exception("❌ DB_URL not found")

url = urlparse.urlparse(db_url)

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


# ✅ GLOBAL QUERY FUNCTION (FIXED)
def execute_query(query, params=None, fetch=False):
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute(query, params or ())
        
        if fetch:
            return cursor.fetchall()
        
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ================= TWILIO =================
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")

client = Client(ACCOUNT_SID, AUTH_TOKEN)


# ================= OTP =================
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
        return jsonify({"status": "error", "message": "Too many OTP requests"})

    otp = str(random.randint(100000, 999999))
    otp_store[phone] = {"otp": otp, "time": time.time(), "attempts": 0}
    otp_send_log.setdefault(phone, []).append(time.time())

    try:
        client.messages.create(
            body=f"Your OTP is {otp}",
            from_=TWILIO_NUMBER,
            to=phone
        )
        return jsonify({"status": "success"})
    except Exception as e:
        print("Twilio error:", e)
        return jsonify({"status": "error"})


@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    phone = normalize_phone(request.form.get('phone', ''))
    otp = request.form.get('otp', '').strip()

    if phone not in otp_store:
        return jsonify({"status": "error", "message": "OTP not found"})

    data = otp_store[phone]

    if time.time() - data["time"] > OTP_EXPIRY:
        del otp_store[phone]
        return jsonify({"status": "error", "message": "Expired"})

    if otp == data["otp"]:
        otp_verified.add(phone)
        del otp_store[phone]
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error"})


@app.route('/submit', methods=['POST'])
def submit():
    name = request.form.get('name', '').strip()
    father = request.form.get('father_name', '').strip()
    caste = request.form.get('caste', '').strip()
    phone = normalize_phone(request.form.get('phone', ''))
    aadhaar = request.form.get('aadhaar', '').strip()

    if not name:
        return jsonify({"status": "error", "message": "Name required"}), 400

    if not validate_phone(phone):
        return jsonify({"status": "error"}), 400

    if not validate_aadhaar(aadhaar):
        return jsonify({"status": "error"}), 400

    if phone not in otp_verified:
        return jsonify({"status": "error", "message": "Verify OTP first"}), 403

    aadhaar_hash = hash_aadhaar(aadhaar)

    try:
        execute_query("""
            INSERT INTO students (name, father_name, caste, phone, aadhaar_hash)
            VALUES (%s, %s, %s, %s, %s)
        """, (name, father, caste, phone, aadhaar_hash))

        otp_verified.discard(phone)

        return jsonify({"status": "success", "message": "Saved"})

    except mysql.connector.IntegrityError:
        return jsonify({"status": "error", "message": "Already exists"}), 409

    except Exception as e:
        print("❌ ERROR:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/students')
def students():
    data = execute_query(
        "SELECT id, name, father_name, caste, phone FROM students",
        fetch=True
    )
    return render_template("students.html", students=data)


# ================= RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)