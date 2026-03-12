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

def send_async_email(app, msg):
    """Sends email on a background thread to prevent Gunicorn timeouts."""
    with app.app_context():
        try:
            mail.send(msg)
            print(f"INFO: Async mail sent to {msg.recipients}")
        except Exception as e:
            print(f"CRITICAL Mail Error: {e}")

# ---------- DATABASE CONNECTION & AUTO-SETUP ----------
def get_db():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL is missing from Render Environment Variables.")
    
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    return psycopg2.connect(db_url, sslmode='require', connect_timeout=5)

@app.before_request
def setup_database():
    """Automatically creates the required tables on the very first visit to prevent 500 errors."""
    if request.endpoint == 'static': 
        return
        
    if not getattr(app, '_db_init_done', False):
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS students (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100),
                    email VARCHAR(100) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    parent_pin VARCHAR(10),
                    usable_balance FLOAT DEFAULT 0,
                    sealed_balance FLOAT DEFAULT 0,
                    emergency_fund FLOAT DEFAULT 0,
                    daily_rate FLOAT DEFAULT 0,
                    days_in_plan INTEGER,
                    streak INTEGER DEFAULT 0,
                    last_day VARCHAR(20),
                    is_verified BOOLEAN DEFAULT FALSE,
                    verification_token VARCHAR(255),
                    recovery_code VARCHAR(20)
                );
                CREATE TABLE IF NOT EXISTS spending (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER REFERENCES students(id),
                    amount FLOAT NOT NULL,
                    date VARCHAR(20) NOT NULL
                );
            """)
            conn.commit()
            app._db_init_done = True
        except Exception as e:
            print(f"DB SETUP ERROR: {e}")
        finally:
            if conn: 
                conn.close()

# ---------- AUTHENTICATION & REGISTRATION ----------

@app.route("/")
def index():
    if 'student_id' in session:
        return redirect(url_for('dashboard'))
    return render_template("index.html")

@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    conn, cur = None, None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE email=%s", (email,))
        user = cur.fetchone()
        
        if user and check_password_hash(user["password"], password):
            if not user.get('is_verified', False):
                flash("Please verify your email first.")
                return redirect(url_for('index'))
            session['student_id'] = user["id"]
            return redirect(url_for('dashboard'))
        flash("Invalid credentials.")
    except Exception as e:
        print(f"Login Error: {e}")
        flash("Login service temporarily unavailable.")
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('index'))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            name = request.form["name"].strip()
            email = request.form["email"].strip().lower()
            password = generate_password_hash(request.form["password"])
            pin = request.form["pin"] 
            token = secrets.token_hex(16)
            recovery_code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            
            conn, cur = None, None
            try:
                conn = get_db()
                cur = conn.cursor()
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
                
                verify_url = url_for('verify_email', token=token, _external=True)
                msg = Message("🚀 Verify Your Comrade Plan", sender=app.config['MAIL_USERNAME'], recipients=[email])
                msg.html = f"<h2>Habari {name}!</h2><p>Recovery Code: <b>{recovery_code}</b></p><a href='{verify_url}'>Verify Account</a>"
                
                Thread(target=send_async_email, args=(app, msg)).start()
                
                flash("Success! Check your email to verify.")
                return redirect(url_for('index'))
            except Exception as e:
                print(f"Reg DB Error: {e}")
                flash("Registration failed. Email may already be in use.")
            finally:
                if cur: cur.close()
                if conn: conn.close()
        except ValueError:
            flash("Please enter valid numbers for money and days.")
            
    return render_template("register.html")

# ---------- DASHBOARD & CORE LOGIC ----------

@app.route("/dashboard")
def dashboard():
    if 'student_id' not in session: 
        return redirect(url_for('index'))
    
    conn, cur = None, None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id=%s", (session['student_id'],))
        s = cur.fetchone()
        
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

# ---------- FINANCIAL OPERATIONS ----------

@app.route("/spend", methods=["POST"])
def spend():
    if 'student_id' not in session: 
        return redirect(url_for('index'))
    try:
        amt = float(request.form["amount"])
        conn, cur = None, None
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT usable_balance FROM students WHERE id=%s", (session['student_id'],))
            balance = cur.fetchone()["usable_balance"]
            
            if amt <= balance:
                cur.execute("UPDATE students SET usable_balance = usable_balance - %s WHERE id=%s", (amt, session['student_id']))
                cur.execute("INSERT INTO spending (student_id, date, amount) VALUES (%s, %s, %s)", (session['student_id'], date.today().isoformat(), amt))
                conn.commit()
            else: 
                flash("Insufficient funds!")
        finally:
            if cur: cur.close()
            if conn: conn.close()
    except ValueError:
        flash("Enter a valid amount.")
    return redirect(url_for('dashboard'))

@app.route("/emergency_release", methods=["POST"])
def emergency_release():
    if 'student_id' not in session: 
        return redirect(url_for('index'))
    pin = request.form.get("pin")
    conn, cur = None, None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id=%s", (session['student_id'],))
        u = cur.fetchone()
        
        if u and str(u['parent_pin']) == str(pin):
            cur.execute("UPDATE students SET usable_balance = usable_balance + emergency_fund, emergency_fund = 0 WHERE id=%s", (u['id'],))
            conn.commit()
            flash("Emergency Buffer Unlocked!")
        else: 
            flash("Incorrect PIN.")
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('dashboard'))

# ---------- ACCOUNT RECOVERY & LEADERBOARD (Restored) ----------

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        token = secrets.token_hex(16)
        conn, cur = None, None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE students SET verification_token=%s WHERE email=%s", (token, email))
            conn.commit()
            if cur.rowcount > 0:
                reset_url = url_for('reset_password', token=token, _external=True)
                msg = Message("🔒 Reset Your Password", sender=app.config['MAIL_USERNAME'], recipients=[email])
                msg.html = f"<h3>Reset Request</h3><p>Click <a href='{reset_url}'>here</a> to reset your password.</p>"
                Thread(target=send_async_email, args=(app, msg)).start()
                flash("Reset link sent to your email.")
            else: 
                flash("Email not found in our system.")
        finally:
            if cur: cur.close()
            if conn: conn.close()
        return redirect(url_for('index'))
    return render_template("reset_password.html")

@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if request.method == "POST":
        new_pw = generate_password_hash(request.form["password"])
        conn, cur = None, None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE students SET password=%s, verification_token=NULL WHERE verification_token=%s", (new_pw, token))
            conn.commit()
            flash("Password updated successfully!")
        finally:
            if cur: cur.close()
            if conn: conn.close()
        return redirect(url_for('index'))
    return render_template("reset_password.html", token=token)

@app.route("/leaderboard")
def leaderboard():
    if 'student_id' not in session: 
        return redirect(url_for('index'))
    conn, cur = None, None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT name, streak FROM students WHERE is_verified=TRUE ORDER BY streak DESC LIMIT 10")
        leaders = cur.fetchall()
        return render_template("leaderboard.html", leaders=leaders)
    finally:
        if cur: cur.close()
        if conn: conn.close()

# ---------- UTILITY & STUB ROUTES ----------

@app.route("/verify/<token>")
def verify_email(token):
    conn, cur = None, None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE students SET is_verified=TRUE, verification_token=NULL WHERE verification_token=%s", (token,))
        conn.commit()
        flash("Verified! You can now login.")
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return redirect(url_for('index'))

@app.route("/test_mail")
def test_mail():
    try:
        msg = Message("Comrade Plan Connection Test", sender=app.config['MAIL_USERNAME'], recipients=[app.config['MAIL_USERNAME']])
        msg.body = "If you are reading this, your Gmail App Password and background threading are working perfectly!"
        mail.send(msg)
        return "<h1>Success!</h1><p>Test email sent to your Gmail address.</p>"
    except Exception as e:
        return f"<h1>Failed!</h1><p>Error details: {str(e)}</p>"

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('index'))

# Adding missing form endpoints to prevent HTML BuildErrors
@app.route("/add_emergency", methods=["POST"])
def add_emergency():
    if 'student_id' not in session: 
        return redirect(url_for('index'))
    try:
        amt = float(request.form["amount"])
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if they actually have enough usable cash to lock away
        cur.execute("SELECT usable_balance FROM students WHERE id=%s", (session['student_id'],))
        balance = cur.fetchone()["usable_balance"]
        
        if amt <= balance:
            cur.execute("UPDATE students SET usable_balance = usable_balance - %s, emergency_fund = emergency_fund + %s WHERE id=%s", (amt, amt, session['student_id']))
            conn.commit()
            flash(f"Successfully locked KES {amt} into emergency buffer!")
        else:
            flash("You don't have enough usable cash to lock that amount.")
    except Exception as e:
        print(f"Add Emergency Error: {e}")
        flash("Error adding to emergency buffer. Please enter a valid number.")
    finally:
        if 'conn' in locals() and conn: conn.close()
    return redirect(url_for('dashboard'))

@app.route("/topup", methods=["POST"])
def topup():
    if 'student_id' not in session: 
        return redirect(url_for('index'))
    try:
        money = float(request.form["money"])
        days = int(request.form["days"])
        buffer_pct = float(request.form.get("buffer_percent", 10)) / 100
        
        # Calculate the new metrics based on the incoming allowance
        new_emergency = round(money * buffer_pct, 2)
        new_daily_rate = round((money - new_emergency) / days, 2)
        new_sealed = round(money - new_emergency - new_daily_rate, 2)
        
        conn = get_db()
        cur = conn.cursor()
        
        # Add the new funds to whatever balance they already have
        cur.execute("""UPDATE students 
                       SET usable_balance = usable_balance + %s,
                           sealed_balance = sealed_balance + %s,
                           emergency_fund = emergency_fund + %s,
                           daily_rate = %s,
                           days_in_plan = %s,
                           last_day = %s
                       WHERE id = %s""",
                    (new_daily_rate, new_sealed, new_emergency, new_daily_rate, days, date.today().isoformat(), session['student_id']))
        conn.commit()
        flash("New cycle started successfully! Funds have been added.")
    except Exception as e:
        print(f"Topup Error: {e}")
        flash("Failed to start new cycle. Check your inputs.")
    finally:
        if 'conn' in locals() and conn: conn.close()
    return redirect(url_for('dashboard'))

@app.route("/reset_plan", methods=["POST"])
def reset_plan():
    if 'student_id' not in session: 
        return redirect(url_for('index'))
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Wipe all financial balances and the streak
        cur.execute("""UPDATE students 
                       SET usable_balance = 0, sealed_balance = 0, emergency_fund = 0, 
                           daily_rate = 0, days_in_plan = 0, streak = 0 
                       WHERE id = %s""", (session['student_id'],))
        conn.commit()
        flash("Plan completely reset. Start a fresh cycle below.")
    except Exception as e:
        print(f"Reset Error: {e}")
        flash("Error resetting plan.")
    finally:
        if 'conn' in locals() and conn: conn.close()
    return redirect(url_for('dashboard'))

@app.route("/request_pin_reset", methods=["POST"])
def request_pin_reset(): return redirect(url_for('dashboard'))

@app.route("/verify_pin_reset", methods=["POST"])
def verify_pin_reset(): return redirect(url_for('dashboard'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
