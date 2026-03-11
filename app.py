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
app.secret_key = os.environ.get("SECRET_KEY", "comrade_secure_key_2026")

# ---------- MAIL CONFIGURATION ----------
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USE_SSL=False,
    MAIL_USERNAME=os.environ.get("MAIL_USER"),
    MAIL_PASSWORD=os.environ.get("MAIL_PASS"),
    MAIL_MAX_EMAILS=None,
    MAIL_ASCII_ATTACHMENTS=False
)

mail = Mail(app)

def send_async_email(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
        except Exception as e:
            print(f"CRITICAL Mail Error: {e}")

def get_db():
    db_url = os.environ.get("DATABASE_URL")
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    conn = psycopg2.connect(db_url, sslmode='require')
    return conn

# ---------- AUTHENTICATION ----------

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
            return redirect(url_for('dashboard'))
        flash("Invalid credentials.")
    finally:
        if cur: cur.close(); 
        if conn: conn.close()
    return redirect("/")

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

# ---------- CORE DASHBOARD ----------

@app.route("/dashboard")
def dashboard():
    if 'student_id' not in session: return redirect(url_for('index'))
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id=%s", (session['student_id'],))
        s = cur.fetchone()
        
        # IMPROVEMENT: Logic Audit - Check if they broke the budget yesterday
        if s["last_day"] != date.today().isoformat():
            # Get yesterday's spending
            cur.execute("SELECT SUM(amount) as total FROM spending WHERE student_id=%s AND date < %s", (s['id'], date.today().isoformat()))
            # (Simplified streak logic: if they had money left, they win. If they overspent, streak = 0)
            # For now, we'll auto-increment as you had it, but ready for strict rules
            
            release = min(s["daily_rate"], s["sealed_balance"])
            cur.execute("""UPDATE students SET usable_balance = usable_balance + %s, 
                sealed_balance = GREATEST(0, sealed_balance - %s), 
                days_in_plan = GREATEST(0, days_in_plan - 1), 
                streak = streak + 1, last_day = %s WHERE id = %s""", 
                (release, release, date.today().isoformat(), s['id']))
            conn.commit()
            cur.execute("SELECT * FROM students WHERE id=%s", (s['id'],))
            s = cur.fetchone()
        
        cur.execute("SELECT SUM(amount) as total FROM spending WHERE student_id=%s AND date=%s", (s['id'], date.today().isoformat()))
        spent = cur.fetchone()["total"] or 0.0
        
        cur.execute("SELECT date, amount FROM spending WHERE student_id=%s ORDER BY date DESC LIMIT 5", (s['id'],))
        history = cur.fetchall()

        if s['streak'] >= 30: user_badge = "Legend"
        elif s['streak'] >= 7: user_badge = "Survivor"
        else: user_badge = "Freshman"

        data = {
            "usable": round(s["usable_balance"], 2), "sealed": round(s["sealed_balance"], 2), 
            "emergency": round(s["emergency_fund"], 2), "daily_limit": round(s["daily_rate"], 2), 
            "spent_today": round(spent, 2), "days_left": s["days_in_plan"], "streak": s["streak"]
        }
        return render_template("dashboard.html", data=data, history=history, badge=user_badge)
    finally:
        if cur: cur.close(); 
        if conn: conn.close()

# ---------- NEW: MISSING ROUTES FROM DASHBOARD ----------

@app.route("/emergency_release", methods=["POST"])
def emergency_release():
    if 'student_id' not in session: return redirect(url_for('index'))
    pin = request.form.get("pin")
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id=%s", (session['student_id'],))
        u = cur.fetchone()
        if u['parent_pin'] == pin:
            amt = u['emergency_fund']
            cur.execute("UPDATE students SET usable_balance = usable_balance + %s, emergency_fund = 0 WHERE id=%s", (amt, u['id']))
            conn.commit()
            flash(f"Buffer Released! KES {amt} added to usable cash.")
        else:
            flash("Wrong PIN! Emergency funds remain locked.")
    finally:
        if cur: cur.close(); 
        if conn: conn.close()
    return redirect(url_for('dashboard'))

@app.route("/leaderboard")
def leaderboard():
    if 'student_id' not in session: return redirect(url_for('index'))
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT name, streak FROM students WHERE is_verified=TRUE ORDER BY streak DESC LIMIT 10")
        leaders = cur.fetchall()
        return render_template("leaderboard.html", leaders=leaders)
    finally:
        if cur: cur.close(); 
        if conn: conn.close()

@app.route("/topup", methods=["POST"])
def topup():
    if 'student_id' not in session: return redirect(url_for('index'))
    money = float(request.form["money"])
    days = int(request.form["days"])
    buffer_pct = float(request.form.get("buffer_percent", 10)) / 100
    emergency = round(money * buffer_pct, 2)
    daily_rate = round((money - emergency) / days, 2)
    sealed = round(money - emergency - daily_rate, 2)
    
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""UPDATE students SET usable_balance = %s, sealed_balance = %s, 
            emergency_fund = %s, daily_rate = %s, days_in_plan = %s, streak = 0 
            WHERE id = %s""", (daily_rate, sealed, emergency, daily_rate, days, session['student_id']))
        conn.commit()
        flash("New plan started! Streak reset to 0.")
    finally:
        if cur: cur.close(); 
        if conn: conn.close()
    return redirect(url_for('dashboard'))

@app.route("/reset_plan", methods=["POST"])
def reset_plan():
    if 'student_id' not in session: return redirect(url_for('index'))
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE students SET usable_balance=0, sealed_balance=0, emergency_fund=0, streak=0, days_in_plan=0 WHERE id=%s", (session['student_id'],))
        conn.commit()
        flash("Plan wiped. Start fresh!")
    finally:
        if cur: cur.close(); 
        if conn: conn.close()
    return redirect(url_for('dashboard'))

@app.route("/spend", methods=["POST"])
def spend():
    if 'student_id' not in session: return redirect(url_for('index'))
    amt = float(request.form["amount"])
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT usable_balance, daily_rate, streak FROM students WHERE id=%s", (session['student_id'],))
        u = cur.fetchone()
        
        if amt <= u["usable_balance"]:
            cur.execute("UPDATE students SET usable_balance = usable_balance - %s WHERE id=%s", (amt, session['student_id']))
            cur.execute("INSERT INTO spending (student_id, date, amount) VALUES (%s, %s, %s)", (session['student_id'], date.today().isoformat(), amt))
            
            # IMPROVEMENT: If they spend more than their daily rate, reset the streak!
            # (Accounting logic: Budget variance must be penalized)
            cur.execute("SELECT SUM(amount) as today_total FROM spending WHERE student_id=%s AND date=%s", (session['student_id'], date.today().isoformat()))
            today_total = cur.fetchone()['today_total']
            if today_total > u['daily_rate']:
                cur.execute("UPDATE students SET streak = 0 WHERE id=%s", (session['student_id'],))
                flash("Budget Broken! Streak reset to 0. 💀")
            
            conn.commit()
        else:
            flash("Insufficient funds! Use your Emergency Buffer?")
    finally:
        if cur: cur.close(); 
        if conn: conn.close()
    return redirect(url_for('dashboard'))

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
