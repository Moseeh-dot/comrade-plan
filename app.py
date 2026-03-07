from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import os
from datetime import date, datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "comrade_discipline_2026")

# ---------- DATABASE SETUP ----------
def get_db():
    conn = sqlite3.connect("budget.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

db = get_db()
cursor = db.cursor()

# Combined Schema: Flask Auth + Your Sealed Balance Logic
cursor.execute("""
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT UNIQUE,
    password TEXT,
    total_allowance REAL,
    sealed_balance REAL,
    usable_balance REAL,
    daily_rate REAL,
    days_remaining INTEGER,
    streak INTEGER DEFAULT 0,
    last_login TEXT,
    emergency_fund REAL DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    date TEXT,
    category TEXT,
    amount REAL,
    type TEXT -- 'spend' or 'release'
)
""")
db.commit()

# ---------- CORE LOGIC HELPERS ----------
def refresh_daily_allowance(student_id):
    """Ported from your original logic: Move daily_rate from Sealed to Usable."""
    cursor.execute("SELECT * FROM students WHERE id=?", (student_id,))
    s = cursor.fetchone()
    today = date.today().isoformat()

    if s['last_login'] != today:
        # Calculate how many days passed (simple version)
        new_usable = s['usable_balance'] + s['daily_rate']
        new_sealed = max(0, s['sealed_balance'] - s['daily_rate'])
        new_days = max(0, s['days_remaining'] - 1)
        new_streak = s['streak'] + 1
        
        cursor.execute("""
            UPDATE students SET 
            usable_balance=?, sealed_balance=?, days_remaining=?, 
            streak=?, last_login=? WHERE id=?
        """, (new_usable, new_sealed, new_days, new_streak, today, student_id))
        db.commit()

# ---------- ROUTES ----------
@app.route("/")
def index():
    return render_template("index.html") if 'user_id' not in session else redirect("/dashboard")

@app.route("/register", methods=["POST"])
def register():
    name = request.form.get("name")
    email = request.form.get("email").lower()
    password = generate_password_hash(request.form.get("password"))
    amount = float(request.form.get("amount"))
    days = int(request.form.get("days"))
    
    # Accounting logic: Initial allocation
    daily_rate = round(amount / days, 2)
    emergency = round(amount * 0.10, 2) # 10% Emergency Buffer
    sealed = amount - daily_rate - emergency
    
    try:
        cursor.execute("""
            INSERT INTO students (name, email, password, total_allowance, sealed_balance, 
            usable_balance, daily_rate, days_remaining, emergency_fund, last_login)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, email, password, amount, sealed, daily_rate, daily_rate, days, emergency, date.today().isoformat()))
        db.commit()
        session['user_id'] = cursor.lastrowid
        return redirect("/dashboard")
    except sqlite3.IntegrityError:
        flash("Email already registered.")
        return redirect("/")

@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email").lower()
    password = request.form.get("password")
    cursor.execute("SELECT * FROM students WHERE email=?", (email,))
    user = cursor.fetchone()
    
    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        refresh_daily_allowance(user['id'])
        return redirect("/dashboard")
    flash("Invalid login.")
    return redirect("/")

@app.route("/dashboard")
def dashboard():
    if 'user_id' not in session: return redirect("/")
    
    cursor.execute("SELECT * FROM students WHERE id=?", (session['user_id'],))
    s = cursor.fetchone()
    
    # Calculate visual data
    progress = int((s['usable_balance'] / s['daily_rate']) * 100) if s['daily_rate'] > 0 else 0
    
    return render_template("dashboard.html", s=s, progress=min(progress, 100))

@app.route("/spend", methods=["POST"])
def spend():
    amount = float(request.form.get("amount"))
    student_id = session['user_id']
    
    cursor.execute("SELECT usable_balance FROM students WHERE id=?", (student_id,))
    current_usable = cursor.fetchone()[0]
    
    if amount <= current_usable:
        new_balance = current_usable - amount
        cursor.execute("UPDATE students SET usable_balance=? WHERE id=?", (new_balance, student_id))
        cursor.execute("INSERT INTO transactions (student_id, date, category, amount, type) VALUES (?, ?, ?, ?, ?)",
                       (student_id, date.today().isoformat(), "General", amount, "spend"))
        db.commit()
    else:
        flash("Insuifficient 'Usable' funds! Check your Vault.")
    
    return redirect("/dashboard")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True, port=5000)