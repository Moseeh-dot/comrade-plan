from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import os
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "comrade_secret_key_2026"

# ---------- DATABASE ----------
def get_db():
    conn = sqlite3.connect("budget.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

db = get_db()
cursor = db.cursor()

# Updated schema for Sealed Balance, Emergency Buffer, and Parent PIN
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
    parent_pin TEXT DEFAULT '1234'
)
""")
cursor.execute("CREATE TABLE IF NOT EXISTS spending (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, date TEXT, amount REAL)")
db.commit()

# ---------- HELPERS ----------
def today_str():
    return date.today().isoformat()

# ---------- ROUTES ----------
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
            buffer_input = float(request.form.get("buffer_percent", 10))
            buffer_ratio = buffer_input / 100
        except ValueError:
            flash("Invalid numbers entered.")
            return redirect("/register")

        # ACCOUNTING LOGIC: User-Defined Buffer
        emergency = round(total_money * buffer_ratio, 2)
        daily_rate = round((total_money - emergency) / days, 2)
        # First day's allowance is usable; the rest is sealed
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
    email, password = request.form["email"].strip().lower(), request.form["password"]
    cursor.execute("SELECT id, password FROM students WHERE email=?", (email,))
    row = cursor.fetchone()
    if row and check_password_hash(row["password"], password):
        session['student_id'] = row["id"]
        return redirect("/dashboard")
    flash("Invalid credentials.")
    return redirect("/")

@app.route("/dashboard")
def dashboard():
    student_id = session.get("student_id")
    if not student_id: return redirect("/")
    
    cursor.execute("SELECT * FROM students WHERE id=?", (student_id,))
    s = cursor.fetchone()
    
    # Check for Daily Release (Ported from your initial idea)
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
        cursor.execute("SELECT * FROM students WHERE id=?", (student_id,))
        s = cursor.fetchone()

    cursor.execute("SELECT SUM(amount) as total FROM spending WHERE student_id=? AND date=?", (student_id, today_str()))
    spent_today = cursor.fetchone()["total"] or 0.0
    
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
    return render_template("dashboard.html", data=data, badge=badge)

@app.route("/spend", methods=["POST"])
def spend():
    amt = float(request.form["amount"])
    cursor.execute("SELECT usable_balance FROM students WHERE id=?", (session['student_id'],))
    usable = cursor.fetchone()[0]
    
    if amt <= usable:
        cursor.execute("UPDATE students SET usable_balance = usable_balance - ? WHERE id=?", (amt, session['student_id']))
        cursor.execute("INSERT INTO spending (student_id, date, amount) VALUES (?,?,?)", (session['student_id'], today_str(), amt))
        db.commit()
    else:
        flash("Vault Locked: Insufficient usable funds.")
    return redirect("/dashboard")

@app.route("/emergency_release", methods=["POST"])
def emergency_release():
    pin = request.form["pin"]
    cursor.execute("SELECT parent_pin, emergency_fund FROM students WHERE id=?", (session['student_id'],))
    res = cursor.fetchone()
    if pin == res["parent_pin"]:
        cursor.execute("UPDATE students SET usable_balance = usable_balance + emergency_fund, emergency_fund = 0 WHERE id=?", (session['student_id'],))
        db.commit()
        flash("Emergency funds released!")
    else:
        flash("Wrong PIN.")
    return redirect("/dashboard")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
@app.route("/leaderboard")
def leaderboard():
    if 'student_id' not in session: return redirect("/")
    
    # Fetch the top 10 students based on their current streak
    cursor.execute("""
        SELECT name, streak 
        FROM students 
        ORDER BY streak DESC 
        LIMIT 10
    """)
    top_comrades = cursor.fetchall()
    
    return render_template("leaderboard.html", top_comrades=top_comrades)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)