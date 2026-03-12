from flask import Flask, render_template, request, redirect, session, flash, url_for
from flask_mail import Mail, Message
import psycopg2
from psycopg2.extras import RealDictCursor
import secrets
import os
import string
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash
from threading import Thread

app = Flask(__name__)
# Security: Prioritize Render Environment Variable
app.secret_key = os.environ.get("SECRET_KEY", "comrade_secure_key_2026")

# ---------- MAIL CONFIGURATION ----------
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USE_SSL=False,
    MAIL_USERNAME=os.environ.get("MAIL_USER"),
    MAIL_PASSWORD=os.environ.get("MAIL_PASS"),
)
mail = Mail(app)

# ---------- ASYNC EMAIL HELPER ----------
def send_async_email(app, msg):
    """Sends mail in background to prevent Gunicorn Worker Timeouts."""
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
    
    # FIX: Added connect_timeout to prevent the app from hanging silently
    conn = psycopg2.connect(db_url, sslmode='require', connect_timeout=5)
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
        try:
            name = request.form["name"].strip()
            email = request.form["email"].strip().lower()
            password = generate_password_hash(request.form["password"])
            pin = request.form["pin"] 
            token = secrets.token_hex(16)
            # Master Recovery Key for account security
            recovery_code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            
            conn, cur = None, None
            try:
                conn = get_db(); cur = conn.cursor()
                # Startup Cleanup Logic
                cur.execute("DELETE FROM students WHERE email = %s AND is_verified = FALSE", (email,))
                conn.commit() 

                money = float(request.form["money"])
                days = int(request.form["days"])
                buffer_pct = float(request.form.get("buffer_percent", 10)) / 100
                
                emergency = round(money * buffer_pct, 2)
                daily_rate = round((money - emergency) / days, 2)
                sealed = round(money - emergency - daily_rate, 2)

                cur.execute("""INSERT INTO students (name, email, password, parent_pin, usable_balance, 
                    sealed_balance, emergency_fund, daily_rate, days_in_plan, last_day, verification_token, recovery_code)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", 
                    (name, email, password, pin, daily_rate, sealed, emergency, daily_rate, days, date.today().isoformat(), token, recovery_code))
                conn.commit()
                
                # FIX: Async Dispatch for Verification Email
                verify_url = url_for('verify_email', token=token, _external=True)
                msg = Message("🚀 Verify Your Comrade Plan", sender=app.config['MAIL_USERNAME'], recipients=[email])
                msg.html = f"<h2>Habari {name}!</h2><p>Recovery Code: <b>{recovery_code}</b></p><a href='{verify_url}'>Verify Account</a>"
                
                Thread(target=send_async_email, args=(app, msg)).start()
                
                flash("Success! Check your email to verify and save your recovery code.")
                return redirect(url_for('index'))
            except Exception as e:
                print(f"Reg Error: {e}")
                flash("Registration failed. Email may be in use.")
            finally:
                if cur: cur.close()
                if conn: conn.close()
        except Exception:
            flash("Please enter valid data.")
            
    return render_template("register.html")

# ---------- DASHBOARD & CORE LOGIC ----------

@app.route("/dashboard")
def dashboard():
    if 'student_id' not in session: return redirect(url_for('index'))
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
            conn.commit()
            cur.execute("SELECT * FROM students WHERE id=%s", (s['id'],))
            s = cur.fetchone()
        
        # Logic for 'spent', 'history', and 'badge' required by your HTML
        cur.execute("SELECT SUM(amount) as total FROM spending WHERE student_id=%s AND date=%s", (s['id'], date.today().isoformat()))
        spent = cur.fetchone()["total"] or 0.0
        
        cur.execute("SELECT date, amount FROM spending WHERE student_id=%s ORDER BY date DESC LIMIT 5", (s['id'],))
        history = cur.fetchall()
        user_badge = "Survivor" if s['streak'] > 7 else "Freshman"

        data = {
            "usable": round(s["usable_balance"], 2), 
            "sealed": round(s["sealed_balance"], 2), 
            "emergency": round(s["emergency_fund"], 2), 
            "daily_limit": round(s["daily_rate"], 2), 
            "spent_today": round(spent, 2), 
            "days_left": s["days_in_plan"], 
            "streak": s["streak"]
        }
        
        return render_template("dashboard.html", data=data, history=history, badge=user_badge)
    except Exception as e:
        print(f"Dashboard Error: {e}")
        return redirect(url_for('logout'))
    finally:
        if cur: cur.close()
        if conn: conn.close()

# ---------- DASHBOARD ACTIONS ----------

@app.route("/emergency_release", methods=["POST"])
def emergency_release():
    if 'student_id' not in session: return redirect(url_for('index'))
    pin = request.form.get("pin")
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id=%s", (session['student_id'],))
        u = cur.fetchone()
        if u and str(u['parent_pin']) == str(pin):
            cur.execute("UPDATE students SET usable_balance = usable_balance + emergency_fund, emergency_fund = 0 WHERE id=%s", (u['id'],))
            conn.commit(); flash("Emergency Buffer Unlocked!")
        else: flash("Incorrect PIN.")
    finally:
        if cur: cur.close(); conn.close()
    return redirect(url_for('dashboard'))

@app.route("/spend", methods=["POST"])
def spend():
    if 'student_id' not in session: return redirect(url_for('index'))
    try:
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
            else: flash("Insufficient funds!")
        finally:
            if cur: cur.close(); conn.close()
    except Exception:
        flash("Invalid amount.")
    return redirect(url_for('dashboard'))

@app.route("/verify/<token>")
def verify_email(token):
    conn, cur = None, None
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE students SET is_verified=TRUE, verification_token=NULL WHERE verification_token=%s", (token,))
        conn.commit(); flash("Verified! You can now login.")
    finally:
        if cur: cur.close(); conn.close()
    return redirect(url_for('index'))

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for('index'))

# Stubs for other features to prevent 404s
@app.route("/leaderboard")
def leaderboard(): 
    return "Leaderboard coming soon!"

@app.route("/topup", methods=["POST"])
def topup(): return redirect(url_for('dashboard'))

@app.route("/reset_plan", methods=["POST"])
def reset_plan(): return redirect(url_for('dashboard'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
