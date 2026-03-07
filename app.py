from flask import Flask, render_template, request, redirect, session, flash
from flask_mail import Mail, Message
import sqlite3
import secrets
import os
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "comrade_discipline_2026")

# ---------- MAIL CONFIGURATION ----------
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USER") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASS")
mail = Mail(app)

# ---------- DATABASE SETUP ----------
def get_db():
    conn = sqlite3.connect("budget.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

db = get_db()
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT UNIQUE,
    password TEXT,
    usable_balance REAL DEFAULT 0,
    sealed_balance REAL DEFAULT 0,
    emergency_fund REAL DEFAULT 0,
    daily_rate REAL DEFAULT 0,
    days_in_plan INTEGER,
    streak INTEGER DEFAULT 0,
    last_day TEXT,
    parent_pin TEXT DEFAULT '1234',
    reset_token TEXT
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS spending (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    student_id INTEGER, 
    date TEXT, 
    amount REAL
)
""")
db.commit()

# ---------- HELPERS ----------
def today_str():
    return date.today().isoformat()

def get_student(student_id):
    cursor.execute("SELECT * FROM students WHERE id=?", (student_id,))
    return cursor.fetchone()

# ---------- AUTH ROUTES ----------
@app.route("/")
def index():
    if 'student_id' in session: return redirect("/dashboard")
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        try:
            total_money = float(request.form["money"])
            days = int(request.form["days"])
            buffer_pct = float(request.form.get("buffer_percent", 10)) / 100
        except:
            flash("Invalid input values.")
            return redirect("/register")

        emergency = round(total_money * buffer_pct, 2)
        daily_rate = round((total_money - emergency) / days, 2)
        sealed = round(total_money - emergency - daily_rate, 2)
        
        hashed = generate_password_hash(password)
        try:
            cursor.execute("""
                INSERT INTO students (name, email, password, usable_balance, sealed_balance, emergency_fund, daily_rate, days_in_plan, streak, last_day)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (name, email, hashed, daily_rate, sealed, emergency, daily_rate, days, today_str()))
            db.commit()
            session['student_id'] = cursor.lastrowid
            return redirect("/dashboard")
        except sqlite3.IntegrityError:
            flash("Email already exists.")
    return render_template("register.html")

@app.route("/login", methods=["POST"])
def login():
    email = request.form["email"].strip().lower()
    password = request.form["password"]
    cursor.execute("SELECT id, password FROM students WHERE email=?", (email,))
    row = cursor.fetchone()
    if row and check_password_hash(row["password"], password):
        session['student_id'] = row["id"]
        return redirect("/dashboard")
    flash("Invalid credentials.")
    return redirect("/")

# ---------- DASHBOARD (COMBINED & CORRECTED) ----------
@app.route("/dashboard")
def dashboard():
    student_id = session.get("student_id")
    if not student_id: return redirect("/")
    
    s = get_student(student_id)
    
    # 1. Daily Release Logic
    if s["last_day"] != today_str():
        release = min(s["daily_rate"], s["sealed_balance"])
        cursor.execute("""
            UPDATE students SET 
            usable_balance = usable_balance + ?, 
            sealed_balance = max(0, sealed_balance - ?),
            days_in_plan = max(0, days_in_plan - 1),
            streak = streak + 1,
            last_day = ? WHERE id = ?
        """, (release, release, today_str(), student_id))
        db.commit()
        s = get_student(student_id)

    # 2. Daily Spending Calculation
    cursor.execute("SELECT SUM(amount) as total FROM spending WHERE student_id=? AND date=?", (student_id, today_str()))
    spent_today = cursor.fetchone()["total"] or 0.0
    
    # 3. Spending History (Last 10 transactions)
    cursor.execute("""
        SELECT date, amount 
        FROM spending 
        WHERE student_id = ? 
        ORDER BY id DESC 
        LIMIT 10
    """, (student_id,))
    history = cursor.fetchall()

    badge = "Iron Discipline" if s["streak"] >= 10 else "Comrade Survivor" if s["streak"] >= 5 else "Budget Rookie"
    
    data = {
        "usable": round(s["usable_balance"], 2),
        "sealed": round(s["sealed_balance"], 2),
        "emergency": round(s["emergency_fund"], 2),
        "daily_limit": round(s["daily_rate"], 2),
        "spent_today": round(spent_today, 2),
        "days_left": s["days_in_plan"],
        "streak": s["streak"]
    }
    return render_template("dashboard.html", data=data, badge=badge, history=history)

# ---------- CORE ACTIONS ----------
@app.route("/spend", methods=["POST"])
def spend():
    amt = float(request.form["amount"])
    s = get_student(session['student_id'])
    if amt <= s["usable_balance"]:
        cursor.execute("UPDATE students SET usable_balance = usable_balance - ? WHERE id=?", (amt, s["id"]))
        cursor.execute("INSERT INTO spending (student_id, date, amount) VALUES (?,?,?)", (s["id"], today_str(), amt))
        db.commit()
    else:
        flash("Vault Locked: Insufficient usable funds.")
    return redirect("/dashboard")

@app.route("/topup", methods=["POST"])
def topup():
    student_id = session.get("student_id")
    try:
        new_money = float(request.form.get("money"))
        new_days = int(request.form.get("days"))
        buffer_pct = float(request.form.get("buffer_percent", 10)) / 100
        if new_money <= 0 or new_days <= 0:
            flash("Amount and days must be positive.")
            return redirect("/dashboard")
    except:
        flash("Invalid input values.")
        return redirect("/dashboard")

    emergency = round(new_money * buffer_pct, 2)
    daily_rate = round((new_money - emergency) / new_days, 2)
    sealed = round(new_money - emergency - daily_rate, 2)
    
    cursor.execute("""
        UPDATE students SET 
        usable_balance = ?, sealed_balance = ?, emergency_fund = ?, 
        daily_rate = ?, days_in_plan = ?, last_day = ?
        WHERE id = ?
    """, (daily_rate, sealed, emergency, daily_rate, new_days, today_str(), student_id))
    db.commit()
    flash(f"Top-up successful! New daily limit: KES {daily_rate}")
    return redirect("/dashboard")

# ---------- EMERGENCY & SECURITY ----------
@app.route("/emergency_release", methods=["POST"])
def emergency_release():
    pin = request.form["pin"]
    s = get_student(session['student_id'])
    if pin == s["parent_pin"]:
        cursor.execute("UPDATE students SET usable_balance = usable_balance + emergency_fund, emergency_fund = 0 WHERE id=?", (s["id"],))
        db.commit()
        flash("Emergency funds released!")
    else:
        flash("Wrong PIN.")
    return redirect("/dashboard")

@app.route("/add_emergency", methods=["POST"])
def add_emergency():
    amt = float(request.form["amount"])
    s = get_student(session['student_id'])
    if amt <= s["usable_balance"]:
        cursor.execute("UPDATE students SET usable_balance = usable_balance - ?, emergency_fund = ? WHERE id=?", (amt, amt, s["id"]))
        db.commit()
        flash("New Emergency Buffer set.")
    else:
        flash("Insufficient funds to set buffer.")
    return redirect("/dashboard")

@app.route("/request_pin_reset", methods=["POST"])
def request_pin_reset():
    s = get_student(session['student_id'])
    token = secrets.token_hex(16)
    cursor.execute("UPDATE students SET reset_token=? WHERE id=?", (token, s['id']))
    db.commit()
    try:
        msg = Message("Comrade Plan: PIN Reset Token", sender=app.config['MAIL_USERNAME'], recipients=[s['email']])
        msg.body = f"Hello {s['name']}, your secure token to reset your Emergency PIN is: {token}"
        mail.send(msg)
        flash("Reset token sent to your email!")
    except:
        flash("Email service error. Check server logs.")
    return redirect("/dashboard")

@app.route("/verify_pin_reset", methods=["POST"])
def verify_pin_reset():
    token_in = request.form.get("token")
    new_pin = request.form.get("new_pin")
    s = get_student(session['student_id'])
    if token_in == s["reset_token"] and s["reset_token"] is not None:
        cursor.execute("UPDATE students SET parent_pin=?, reset_token=NULL WHERE id=?", (new_pin, s['id']))
        db.commit()
        flash("PIN reset successful!")
    else:
        flash("Invalid token.")
    return redirect("/dashboard")

# ---------- SOCIAL & DANGER ZONE ----------
@app.route("/leaderboard")
def leaderboard():
    cursor.execute("SELECT name, streak FROM students ORDER BY streak DESC LIMIT 10")
    top_comrades = cursor.fetchall()
    return render_template("leaderboard.html", top_comrades=top_comrades)

@app.route("/reset_plan", methods=["POST"])
def reset_plan():
    cursor.execute("""
        UPDATE students SET usable_balance=0, sealed_balance=0, emergency_fund=0, 
        daily_rate=0, days_in_plan=0, streak=0, last_day=? WHERE id=?
    """, (today_str(), session['student_id']))
    db.commit()
    flash("Plan Reset. Start a new mission.")
    return redirect("/dashboard")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)