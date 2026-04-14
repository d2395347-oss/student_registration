from flask import Flask, render_template, request, jsonify
import random
import time
import os
import requests

app = Flask(__name__)

# ---------------- OTP STORAGE ----------------
otp_store = {}
OTP_EXPIRY = 300
RESEND_INTERVAL = 30


# ---------------- FAST2SMS ----------------
def send_fast2sms(phone, otp):
    print("🔥 INSIDE FAST2SMS FUNCTION")

    url = "https://www.fast2sms.com/dev/bulkV2"

    payload = {
        "variables_values": otp,
        "route": "otp",
        "numbers": phone
    }

    headers = {
        "authorization": "YOUR_FAST2SMS_API_KEY",  # 🔴 replace this
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)

        print("🔥 FAST2SMS STATUS CODE:", response.status_code)
        print("🔥 FAST2SMS RESPONSE:", response.text)

    except Exception as e:
        print("❌ FAST2SMS ERROR:", str(e))


# ---------------- OTP GENERATION ----------------
def generate_otp(phone):
    otp = str(random.randint(100000, 999999))

    otp_store[phone] = {
        "otp": otp,
        "time": time.time()
    }

    print("🔥 GENERATED OTP FOR DEBUG:", otp)

    send_fast2sms(phone, otp)
    return otp


# ---------------- OTP VERIFY ----------------
def verify_otp_func(phone, user_otp):
    if phone not in otp_store:
        return False, "No OTP sent"

    data = otp_store[phone]

    if time.time() - data["time"] > OTP_EXPIRY:
        return False, "OTP expired"

    if user_otp == data["otp"]:
        return True, "Verified"

    return False, "Invalid OTP"


# ---------------- RESEND CHECK ----------------
def can_resend(phone):
    if phone not in otp_store:
        return True

    return (time.time() - otp_store[phone]["time"]) >= RESEND_INTERVAL


# ---------------- UTILITIES ----------------
def clean_phone(phone):
    phone = phone.strip()

    if phone.startswith("+91"):
        phone = phone[3:]

    phone = phone.replace(" ", "")

    return phone


def mask_aadhaar(aadhaar):
    return "XXXXXXXX" + aadhaar[-4:]


def validate_aadhaar(aadhaar):
    return len(aadhaar) == 12 and aadhaar.isdigit() and aadhaar[0] not in ['0', '1']


# ---------------- ROUTES ----------------

@app.route('/')
def home():
    return render_template('form.html')


@app.route('/send_otp', methods=['POST'])
def send_otp():
    print("🔥 SEND OTP HIT")

    phone = request.form['phone']
    phone = clean_phone(phone)

    print("📱 CLEAN PHONE:", phone)

    if not can_resend(phone):
        return jsonify({"status": "error", "message": "Wait before resending OTP"})

    generate_otp(phone)

    print("🔥 OTP PROCESS COMPLETED")

    return jsonify({"status": "success", "message": "OTP Sent"})


@app.route('/verify_otp', methods=['POST'])
def verify():
    phone = clean_phone(request.form['phone'])
    otp = request.form['otp'].strip()

    valid, message = verify_otp_func(phone, otp)

    return jsonify({"status": valid, "message": message})


@app.route('/submit', methods=['POST'])
def submit():
    name = request.form['name']
    father_name = request.form['father_name']
    caste = request.form['caste']
    email = request.form['email']
    phone = request.form['phone']
    aadhaar = request.form['aadhaar']

    if not validate_aadhaar(aadhaar):
        return "Invalid Aadhaar"

    masked = mask_aadhaar(aadhaar)

    print("✅ FORM SUBMITTED:", name, phone)

    return "Form received successfully"


# ---------------- RUN APP ----------------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)