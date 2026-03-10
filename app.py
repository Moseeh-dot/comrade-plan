from flask import Flask, render_template, request, redirect, session, flash, url_for
from flask_mail import Mail, Message
import psycopg2
from psycopg2.extras import RealDictCursor
import secrets
import os
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash
from threading import Thread

app = Flask(__name__)
# Security: Prioritize Render Environment Variable
app.secret_key = os.environ.get("SECRET_KEY", "comrade_secure_key_2026")

# ---------- MAIL CONFIGURATION ----------
# ---------- UPDATED MAIL CONFIGURATION ----------
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=2525,
    MAIL_USE_TLS=True,
    MAIL_USE_SSL=False,  # Force SSL False to avoid port conflicts
    MAIL_USERNAME=os.environ.get("MAIL_USER"),
    MAIL_PASSWORD=os.environ.get("MAIL_PASS"),
    MAIL_MAX_EMAILS=None,
    MAIL_ASCII_ATTACHMENTS=False
)

mail = Mail(app)

# ---------- ASYNC EMAIL HELPER ----------
def send_async_email(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
        except Exception as e:
            print(f"CRITICAL Mail Error: {e}")

# ---------- DATABASE CONNECTION ----------
def get_db():
    db_url = os.environ.get("DATABASE_URL")
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    conn = psycopg2.connect(db_url, sslmode='require')
    return conn

# ---------- AUTHENTICATION & REGISTRATION ----------

@app.route("/")
def index():
    if 'student_id' in session:
        return redirect(url_for('dashboard'))
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = generate_password_hash(request.form["password"])
        pin = request.form["pin"] 
        token = secrets.token_hex(16)
        conn, cur = None, None

        try:
            conn = get_db(); cur = conn.cursor()
            # AUTO-CLEANUP: Delete failed, unverified attempts
            cur.execute("DELETE FROM students WHERE email = %s AND is_verified = FALSE", (email,))
            conn.commit() 

            money, days = float(request.form["money"]), int(request.form["days"])
            buffer_pct = float(request.form.get("buffer_percent", 10)) / 100
            emergency = round(money * buffer_pct, 2)
            daily_rate = round((money - emergency) / days, 2)
            sealed = round(money - emergency - daily_rate, 2)

            cur.execute("""INSERT INTO students (name, email, password, parent_pin, usable_balance, 
                sealed_balance, emergency_fund, daily_rate, days_in_plan, last_day, verification_token)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", 
                (name, email, password, pin, daily_rate, sealed, emergency, daily_rate, days, date.today().isoformat(), token))
            conn.commit()
            
            verify_url = url_for('verify_email', token=token, _external=True)
            msg = Message("🚀 Verify Your Comrade Plan", sender=app.config['MAIL_USERNAME'], recipients=[email])
            msg.html = f"<h2>Habari {name}!</h2><p>Click below to verify:</p><a href='{verify_url}'>Verify Account</a>"
            Thread(target=send_async_email, args=(app, msg)).start()
            
            flash("Success! Check your email to verify."); return redirect("/")
        except Exception as e:
            flash("Registration failed. Email may be in use."); print(f"Reg Error: {e}")
        finally:
            if cur: cur.close(); 
            if conn: conn.close()
    return render_template("register.html")

# ---------- PASSWORD RESET ROUTES ----------

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        token = secrets.token_hex(16)
        conn, cur = None, None
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute("UPDATE students SET verification_token=%s WHERE email=%s", (token, email))
            conn.commit()
            if cur.rowcount > 0:
                reset_url = url_for('reset_password', token=token, _external=True)
                msg = Message("🔒 Reset Your Password", sender=app.config['MAIL_USERNAME'], recipients=[email])
                msg.html = f"<h3>Reset Request</h3><p>Click <a href='{reset_url}'>here</a> to reset your password.</p>"
                Thread(target=send_async_email, args=(app, msg)).start()
                flash("Reset link sent to your email.")
            else:
                flash("Email not found.")
        finally:
            if cur: cur.close(); 
            if conn: conn.close()
        return redirect("/")
    return render_template("forgot_password.html")

@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if request.method == "POST":
        new_pw = generate_password_hash(request.form["password"])
        conn, cur = None, None
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute("UPDATE students SET password=%s, verification_token=NULL WHERE verification_token=%s", (new_pw, token))
            conn.commit()
            flash("Password updated! Please login.")
        finally:
            if cur: cur.close(); 
            if conn: conn.close()
        return redirect("/")
    return render_template("reset_password.html", token=token)

# ---------- DASHBOARD & CORE LOGIC ----------

@app.route("/verify/<token>")
def verify_email(token):
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE students SET is_verified=TRUE, verification_token=NULL WHERE verification_token=%s", (token,))
        conn.commit()
        flash("Verified! You can now login.") if cur.rowcount > 0 else flash("Invalid link.")
    finally:
        if cur: cur.close(); 
        if conn: conn.close()
    return redirect("/")

@app.route("/login", methods=["POST"])
def login():
    email, password = request.form["email"].strip().lower(), request.form["password"]
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE email=%s", (email,))
        user = cur.fetchone()
        if user and check_password_hash(user["password"], password):
            if not user['is_verified']: flash("Please verify your email."); return redirect("/")
            session['student_id'] = user["id"]
            return redirect("/dashboard")
        flash("Invalid credentials.")
    finally:
        if cur: cur.close(); 
        if conn: conn.close()
    return redirect("/")

@app.route("/dashboard")
def dashboard():
    if 'student_id' not in session: return redirect("/")
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id=%s", (session['student_id'],))
        s = cur.fetchone()
        
        # Daily Release Logic
        if s["last_day"] != date.today().isoformat():
            release = min(s["daily_rate"], s["sealed_balance"])
            cur.execute("""UPDATE students SET usable_balance = usable_balance + %s, 
                sealed_balance = GREATEST(0, sealed_balance - %s), 
                days_in_plan = GREATEST(0, days_in_plan - 1), 
                streak = streak + 1, last_day = %s WHERE id = %s""", 
                (release, release, date.today().isoformat(), s['id']))
            conn.commit(); cur.execute("SELECT * FROM students WHERE id=%s", (s['id'],)); s = cur.fetchone()
        
        cur.execute("SELECT SUM(amount) as total FROM spending WHERE student_id=%s AND date=%s", (s['id'], date.today().isoformat()))
        spent = cur.fetchone()["total"] or 0.0
        data = {"usable": round(s["usable_balance"], 2), "sealed": round(s["sealed_balance"], 2), "emergency": round(s["emergency_fund"], 2), "daily_limit": round(s["daily_rate"], 2), "spent_today": round(spent, 2), "days_left": s["days_in_plan"], "streak": s["streak"]}
        return render_template("dashboard.html", data=data)
    finally:
        if cur: cur.close(); 
        if conn: conn.close()

@app.route("/spend", methods=["POST"])
def spend():
    amt = float(request.form["amount"])
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT usable_balance FROM students WHERE id=%s", (session['student_id'],))
        balance = cur.fetchone()["usable_balance"]
        if amt <= balance:
            cur.execute("UPDATE students SET usable_balance = usable_balance - %s WHERE id=%s", (amt, session['student_id']))
            cur.execute("INSERT INTO spending (student_id, date, amount) VALUES (%s, %s, %s)", (session['student_id'], date.today().isoformat(), amt))
            conn.commit()
        else:
            flash("Insufficient funds for today!")
    finally:
        if cur: cur.close(); 
        if conn: conn.close()
    return redirect("/dashboard")

@app.route("/logout")
def logout():
    session.clear(); return redirect("/")

@app.route("/test_mail")
def test_mail():
    try:
        msg = Message("Connection Test", sender=app.config['MAIL_USERNAME'], recipients=[app.config['MAIL_USERNAME']])
        msg.body = "Working!"
        mail.send(msg)
        return "<h1>Success!</h1>"
    except Exception as e:
        return f"<h1>Failed!</h1><p>{str(e)}</p>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
