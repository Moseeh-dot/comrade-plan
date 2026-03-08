from flask import Flask, render_template, request, redirect, session, flash, url_for
from flask_mail import Mail, Message
import psycopg2
from psycopg2.extras import RealDictCursor
import secrets
import os
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Security: Prioritize Render Environment Variable for the secret key
app.secret_key = os.environ.get("SECRET_KEY", "comrade_secure_key_2026")

# ---------- MAIL CONFIGURATION (Verification & PIN Reset) ----------
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME=os.environ.get("MAIL_USER"),
    MAIL_PASSWORD=os.environ.get("MAIL_PASS")
)
mail = Mail(app)

# ---------- DATABASE CONNECTION (PostgreSQL) ----------
def get_db():
    # Use SSL mode 'require' as enforced by Render PostgreSQL
    conn = psycopg2.connect(os.environ.get("DATABASE_URL"), sslmode='require')
    return conn

# ---------- AUTHENTICATION & REGISTRATION ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = generate_password_hash(request.form["password"])
        # Fix: User now sets their own unique Emergency PIN at signup
        pin = request.form["pin"] 
        token = secrets.token_hex(16)
        
        try:
            total_money = float(request.form["money"])
            days = int(request.form["days"])
            buffer_pct = float(request.form.get("buffer_percent", 10)) / 100
        except (ValueError, TypeError):
            flash("Invalid financial data entered.")
            return redirect("/register")

        # ACCOUNTING LOGIC: Strategic Capital Split
        emergency = round(total_money * buffer_pct, 2)
        daily_rate = round((total_money - emergency) / days, 2)
        sealed = round(total_money - emergency - daily_rate, 2)

        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO students (name, email, password, parent_pin, usable_balance, 
                sealed_balance, emergency_fund, daily_rate, days_in_plan, last_day, verification_token)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (name, email, password, pin, daily_rate, sealed, emergency, daily_rate, days, date.today().isoformat(), token))
            conn.commit()
            
            # Send Verification Email
            verify_url = url_for('verify_email', token=token, _external=True)
            msg = Message("Verify Your Comrade Plan Account", 
                          sender=app.config['MAIL_USERNAME'], 
                          recipients=[email])
            msg.body = f"Habari {name}! Click the link to verify your account and start your plan: {verify_url}"
            mail.send(msg)
            
            flash("Registration successful! Check your email to verify your account.")
            return redirect("/")
        except Exception as e:
            flash("Registration failed. Email may already be in use.")
        finally:
            cur.close()
            conn.close()
    return render_template("register.html")

@app.route("/verify/<token>")
def verify_email(token):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE students SET is_verified=TRUE, verification_token=NULL WHERE verification_token=%s", (token,))
    conn.commit()
    if cur.rowcount > 0:
        flash("Email verified successfully! You can now login.")
    else:
        flash("Verification link is invalid or expired.")
    cur.close()
    conn.close()
    return redirect("/")

@app.route("/login", methods=["POST"])
def login():
    email = request.form["email"].strip().lower()
    password = request.form["password"]
    
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM students WHERE email=%s", (email,))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if user and check_password_hash(user["password"], password):
        if not user['is_verified']:
            flash("Account not verified. Please check your email.")
            return redirect("/")
        session['student_id'] = user["id"]
        return redirect("/dashboard")
    
    flash("Invalid email or password.")
    return redirect("/")

# ---------- DASHBOARD CORE ----------
@app.route("/dashboard")
def dashboard():
    if 'student_id' not in session: return redirect("/")
    
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM students WHERE id=%s", (session['student_id'],))
    s = cur.fetchone()
    
    # Daily Auto-Release Logic
    if s["last_day"] != date.today().isoformat():
        release = min(s["daily_rate"], s["sealed_balance"])
        cur.execute("""
            UPDATE students SET 
            usable_balance = usable_balance + %s, 
            sealed_balance = GREATEST(0, sealed_balance - %s),
            days_in_plan = GREATEST(0, days_in_plan - 1),
            streak = streak + 1,
            last_day = %s WHERE id = %s
        """, (release, release, date.today().isoformat(), s['id']))
        conn.commit()
        # Refresh local data variable
        cur.execute("SELECT * FROM students WHERE id=%s", (s['id'],))
        s = cur.fetchone()

    cur.execute("SELECT SUM(amount) as total FROM spending WHERE student_id=%s AND date=%s", (s['id'], date.today().isoformat()))
    spent_today = cur.fetchone()["total"] or 0.0
    
    data = {
        "usable": round(s["usable_balance"], 2),
        "sealed": round(s["sealed_balance"], 2),
        "emergency": round(s["emergency_fund"], 2),
        "daily_limit": round(s["daily_rate"], 2),
        "spent_today": round(spent_today, 2),
        "days_left": s["days_in_plan"],
        "streak": s["streak"]
    }
    
    badge = "Iron Discipline" if s["streak"] >= 10 else "Budget Rookie"
    
    cur.close()
    conn.close()
    return render_template("dashboard.html", data=data, badge=badge)

# ---------- FINANCIAL OPERATIONS ----------
@app.route("/spend", methods=["POST"])
def spend():
    try:
        amt = float(request.form["amount"])
        if amt <= 0: raise ValueError
    except:
        flash("Please enter a positive numeric amount.")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT usable_balance FROM students WHERE id=%s", (session['student_id'],))
    balance = cur.fetchone()["usable_balance"]

    if amt <= balance:
        cur.execute("UPDATE students SET usable_balance = usable_balance - %s WHERE id=%s", (amt, session['student_id']))
        cur.execute("INSERT INTO spending (student_id, date, amount) VALUES (%s, %s, %s)", (session['student_id'], date.today().isoformat(), amt))
        conn.commit()
    else:
        flash("You have exceeded your usable balance for today!")
    
    cur.close()
    conn.close()
    return redirect("/dashboard")

@app.route("/emergency_release", methods=["POST"])
def emergency_release():
    pin_attempt = request.form.get("pin")
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT parent_pin, emergency_fund FROM students WHERE id=%s", (session['student_id'],))
    s = cur.fetchone()

    if pin_attempt == s["parent_pin"]:
        cur.execute("UPDATE students SET usable_balance = usable_balance + emergency_fund, emergency_fund = 0 WHERE id=%s", (session['student_id'],))
        conn.commit()
        flash("Emergency funds released to usable balance!")
    else:
        flash("Incorrect PIN. Access denied.")
    
    cur.close()
    conn.close()
    return redirect("/dashboard")

@app.route("/topup", methods=["POST"])
def topup():
    """Logic to restart the plan cycle"""
    try:
        money = float(request.form["money"])
        days = int(request.form["days"])
        buffer_pct = float(request.form.get("buffer_percent", 10)) / 100
    except:
        flash("Invalid values provided.")
        return redirect("/dashboard")

    emergency = round(money * buffer_pct, 2)
    daily = round((money - emergency) / days, 2)
    sealed = round(money - emergency - daily, 2)
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE students SET usable_balance=%s, sealed_balance=%s, emergency_fund=%s, 
        daily_rate=%s, days_in_plan=%s, last_day=%s WHERE id=%s
    """, (daily, sealed, emergency, daily, days, date.today().isoformat(), session['student_id']))
    conn.commit()
    cur.close()
    conn.close()
    flash("New Cycle Started!")
    return redirect("/dashboard")

@app.route("/reset_plan", methods=["POST"])
def reset_plan():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE students SET usable_balance=0, sealed_balance=0, emergency_fund=0, streak=0, days_in_plan=0 WHERE id=%s", (session['student_id'],))
    conn.commit()
    cur.close()
    conn.close()
    flash("Plan has been wiped.")
    return redirect("/dashboard")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    # For local development; Render will use gunicorn
    app.run(host="0.0.0.0", port=10000, debug=True)