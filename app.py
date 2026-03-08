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

# ---------- MAIL CONFIGURATION ----------
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
    # Fetch the Render URL from environment
    db_url = os.environ.get("DATABASE_URL")
    
    # DEBUG FIX: SQLAlchemy/Psycopg often requires 'postgresql://' instead of 'postgres://'
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    # Connect with SSL mode required for Render PostgreSQL
    conn = psycopg2.connect(db_url, sslmode='require')
    return conn

# ---------- ROUTES & AUTHENTICATION ----------

@app.route("/")
def index():
    """FIXED: Added root route to prevent 404 error on homepage"""
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
        
        conn = get_db()
        cur = conn.cursor()

        try:
            # --- STARTUP CLEANUP LOGIC ---
            # This deletes any old, unverified attempt for this email 
            # so the student doesn't get the "Email in use" error.
            cur.execute("DELETE FROM students WHERE email = %s AND is_verified = FALSE", (email,))
            conn.commit() 
            # -----------------------------

            total_money = float(request.form["money"])
            days = int(request.form["days"])
            buffer_pct = float(request.form.get("buffer_percent", 10)) / 100

            emergency = round(total_money * buffer_pct, 2)
            daily_rate = round((total_money - emergency) / days, 2)
            sealed = round(total_money - emergency - daily_rate, 2)

            cur.execute("""
                INSERT INTO students (name, email, password, parent_pin, usable_balance, 
                sealed_balance, emergency_fund, daily_rate, days_in_plan, last_day, verification_token)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (name, email, password, pin, daily_rate, sealed, emergency, daily_rate, days, date.today().isoformat(), token))
            conn.commit()
            
            # Send Verification Email
            # Send Professional Verification Email
            verify_url = url_for('verify_email', token=token, _external=True)
            msg = Message("🚀 Verify Your Comrade Plan Account", 
              sender=app.config['MAIL_USERNAME'], 
              recipients=[email])

            # HTML Body for a professional "Startup" feel
            msg.html = f"""
             <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; border: 1px solid #ddd; padding: 20px; border-radius: 10px;">
                <h2 style="color: #2c3e50; text-align: center;">Welcome to Comrade Plan KE!</h2>
                <p>Habari {name},</p>
                <p>You're one step away from mastering your university budget. Click the button below to verify your account and unlock your daily funds.</p>
            <div style="text-align: center; margin: 30px 0;">
        <a href="{verify_url}" style="background-color: #e67e22; color: white; padding: 15px 25px; text-decoration: none; border-radius: 5px; font-weight: bold;">Verify My Account</a>
    </div>
        <p style="font-size: 12px; color: #7f8c8d;">If you didn't sign up for Comrade Plan, please ignore this email.</p>
       <hr style="border: 0; border-top: 1px solid #eee;">
       <p style="text-align: center; font-weight: bold;">Financially Disciplined. Comrade Strong.</p>
    </div>
"""
            mail.send(msg)
            
            flash("Success! Check your email to verify your account.")
            return redirect("/")
            
        except Exception as e:
            # If the account WAS verified (TRUE), the DELETE above won't touch it,
            # and this block will catch the 'Email in Use' error for real accounts.
            flash("Registration failed. This email is already verified and in use.")
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
    
    cur.close()
    conn.close()
    return render_template("dashboard.html", data=data)

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
        flash("Emergency funds released!")
    else:
        flash("Incorrect PIN.")
    
    cur.close()
    conn.close()
    return redirect("/dashboard")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
@app.route("/test_mail")
def test_mail():
    try:
        msg = Message("Startup Connection Test",
                      sender=app.config['MAIL_USERNAME'],
                      recipients=[app.config['MAIL_USERNAME']]) # Sends to yourself
        msg.body = "If you are reading this, your Gmail App Password is working!"
        mail.send(msg)
        return "<h1>Success!</h1><p>Test email sent to your Gmail address.</p>"
    except Exception as e:
        return f"<h1>Failed!</h1><p>Error: {str(e)}</p>"
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)