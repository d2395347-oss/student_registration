from flask import Flask, render_template, request, jsonify
import mysql.connector
import random
import time
import os

app = Flask(__name__)

# ----------- DATABASE -----------
# db = mysql.connector.connect(
#     host="localhost",
#     user="root",
#     password="Narayan@1234",  # change this
#     database="student_db"
# )

# cursor = db.cursor()

# ----------- OTP STORAGE -----------
otp_store = {}
OTP_EXPIRY = 300
RESEND_INTERVAL = 30

# ----------- FUNCTIONS -----------
def send_fast2sms(phone, otp):
    url = "https://www.fast2sms.com/dev/bulkV2"

    payload = {
        "route": "otp",
        "variables_values": otp,
        "numbers": phone
    }

    headers = {
        "wczKj6W8ohImGBVxiH0q91rCtUnYNgyApMsFvJOR2b4dZTQSkfuTgilfAGWVyt8EN19SvD3bMcrF02Yj",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)
    print(response.text)

def generate_otp(phone):
    otp = str(random.randint(100000, 999999))
    otp_store[phone] = {
        "otp": otp,
        "time": time.time()
    }
    send_fast2sms(phone, otp) # shown in terminal
    return otp


def verify_otp(phone, user_otp):
    if phone not in otp_store:
        return False, "No OTP sent"

    data = otp_store[phone]

    if time.time() - data["time"] > OTP_EXPIRY:
        return False, "OTP expired"

    if user_otp == data["otp"]:
        return True, "Verified"

    return False, "Invalid OTP"


def can_resend(phone):
    if phone not in otp_store:
        return True

    if time.time() - otp_store[phone]["time"] < RESEND_INTERVAL:
        return False

    return True


def mask_aadhaar(aadhaar):
    return "XXXXXXXX" + aadhaar[-4:]


def validate_aadhaar(aadhaar):
    return len(aadhaar) == 12 and aadhaar.isdigit() and aadhaar[0] not in ['0','1']

# ----------- ROUTES -----------

@app.route('/')
def home():
    return render_template('form.html')


@app.route('/send_otp', methods=['POST'])
def send_otp():
    phone = request.form['phone']

    if not can_resend(phone):
        return jsonify({"status": "error", "message": "Wait before resend"})

    generate_otp(phone)
    return jsonify({"status": "success", "message": "OTP Sent"})


@app.route('/verify_otp', methods=['POST'])
def verify():
    phone = request.form['phone']
    otp = request.form['otp']

    valid, message = verify_otp(phone, otp)

    return jsonify({"status": valid, "message": message})


@app.route('/submit', methods=['POST'])
def submit():
    name = request.form['name']
    father_name = request.form['father_name']
    caste = request.form['caste']
    email = request.form['email']
    phone = request.form['phone']
    aadhaar = request.form['aadhaar']

    return "Form received successfully (Render test working)"

    if not validate_aadhaar(aadhaar):
        return "Invalid Aadhaar"

    masked = mask_aadhaar(aadhaar)

    query = "INSERT INTO students (name, father_name, caste, email, phone, aadhaar) VALUES (%s,%s,%s,%s,%s,%s)"
    values = (name, father_name, caste, email, phone, masked)

    cursor.execute(query, values)
    db.commit()

    return "Registration Successful"


if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)