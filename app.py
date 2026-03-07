from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "supersecretkey123"

# ---------- DATABASE ----------
# If you have an old corrupted DB or different schema, delete it and restart.
conn = sqlite3.connect("budget.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Create table with days_in_plan column (persisted)
cursor.execute("""
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT UNIQUE,
    password TEXT,
    balance REAL,
    days_in_plan INTEGER,
    streak INTEGER,
    last_day TEXT
)
""")
# Add forgot password columns if they don't exist
try:
    cursor.execute("ALTER TABLE students ADD COLUMN reset_token TEXT")
except sqlite3.OperationalError:
    # Column already exists, ignore
    pass

try:
    cursor.execute("ALTER TABLE students ADD COLUMN token_expiry TEXT")
except sqlite3.OperationalError:
    # Column already exists, ignore
    pass

conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS spending (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    date TEXT,
    amount REAL
)
""")
conn.commit()

# ---------- HELPERS ----------
def get_student(student_id):
    cursor.execute("SELECT * FROM students WHERE id=?", (student_id,))
    row = cursor.fetchone()
    if row:
        return {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "balance": row["balance"],
            "days_in_plan": row["days_in_plan"] if row["days_in_plan"] is not None else 0,
            "streak": row["streak"],
            "last_day": row["last_day"]
        }
    return None

def update_student(student):
    cursor.execute("""
        UPDATE students
        SET balance=?, days_in_plan=?, streak=?, last_day=?
        WHERE id=?
    """, (student["balance"], student.get("days_in_plan"), student["streak"], student["last_day"], student["id"]))
    conn.commit()

def today_str():
    return date.today().isoformat()

def compute_daily_limit(balance, days):
    try:
        days = int(days)
    except Exception:
        days = 0
    if days > 0:
        return round(balance / days, 2)
    return float(balance)

# ---------- ROUTES ----------
@app.route("/")
def index():
    if 'student_id' in session:
        return redirect("/dashboard")
    return render_template("index.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        try:
            money = float(request.form["money"])
            days = int(request.form["days"])
            if money < 0 or days <= 0:
                flash("Enter a positive amount and days > 0.")
                return redirect("/register")
        except Exception:
            flash("Invalid money or days value.")
            return redirect("/register")

        hashed = generate_password_hash(password)
        try:
            cursor.execute("""
                INSERT INTO students (name,email,password,balance,days_in_plan,streak,last_day)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, email, hashed, money, days, 0, today_str()))
            conn.commit()
            student_id = cursor.lastrowid

            # Set session values from persisted data
            session['student_id'] = student_id
            session['days_in_plan'] = days
            session['daily_limit'] = compute_daily_limit(money, days)
            return redirect("/dashboard")
        except sqlite3.IntegrityError:
            flash("Email already exists.")
            return redirect("/register")
    return render_template("register.html")

@app.route("/login", methods=["POST"])
def login():
    email = request.form["email"].strip().lower()
    password = request.form["password"]
    cursor.execute("SELECT id,password FROM students WHERE email=?", (email,))
    row = cursor.fetchone()
    if row:
        if check_password_hash(row["password"], password):
            student = get_student(row["id"])
            session['student_id'] = student["id"]
            # restore persisted days_in_plan and daily_limit
            session['days_in_plan'] = student["days_in_plan"] if student["days_in_plan"] is not None else 1
            session['daily_limit'] = compute_daily_limit(student["balance"], session['days_in_plan'])
            return redirect("/dashboard")
        else:
            flash("Incorrect password.")
            return redirect("/")
    else:
        flash("Email not found. Please register.")
        return redirect("/")

@app.route("/dashboard")
def dashboard():
    student_id = session.get("student_id")
    if not student_id:
        return redirect("/")

    student = get_student(student_id)
    if not student:
        session.clear()
        flash("User not found. Please login again.")
        return redirect("/")

    # Ensure session days_in_plan exists (fallback to DB)
    if 'days_in_plan' not in session or session.get('days_in_plan') in (None, 0):
        session['days_in_plan'] = student["days_in_plan"] or 1

    # Daily reset at midnight: if last_day != today, increase streak and update last_day
    if student["last_day"] != today_str():
        student["streak"] = (student["streak"] or 0) + 1
        student["last_day"] = today_str()
        # Persist days_in_plan back to DB if missing
        if student["days_in_plan"] is None or student["days_in_plan"] == 0:
            student["days_in_plan"] = session.get("days_in_plan", 1)
        update_student(student)

    # Calculate spent today
    cursor.execute("SELECT SUM(amount) as total FROM spending WHERE student_id=? AND date=?", (student_id, today_str()))
    spent_today = cursor.fetchone()["total"] or 0.0

    # Ensure daily_limit derived from latest persisted values
    session['daily_limit'] = compute_daily_limit(student["balance"], session.get('days_in_plan', 1))

    # Determine badge
    badge = "Budget Rookie"
    if (student["streak"] or 0) >= 10:
        badge = "Iron Discipline"
    elif (student["streak"] or 0) >= 5:
        badge = "Comrade Survivor"

    # Overspending warning
    warning = ""
    if session['daily_limit'] > 0 and spent_today > session['daily_limit']:
        warning = "⚠ You exceeded today's limit!"

    # Survival days (safe)
    if session['daily_limit'] > 0:
        survival_days = int(student["balance"] // session['daily_limit'])
    else:
        survival_days = 0

    data = {
        "balance": round(student["balance"], 2),
        "streak": student["streak"] or 0,
        "spent_today": round(spent_today, 2),
        "daily_limit": round(session['daily_limit'], 2),
        "days_in_plan": int(session.get('days_in_plan', 1)),
        "survival_days": survival_days
    }

    return render_template("dashboard.html", data=data, badge=badge, warning=warning)

@app.route("/spend", methods=["POST"])
def spend():
    student_id = session.get("student_id")
    if not student_id:
        return redirect("/")

    try:
        amount = float(request.form["amount"])
        if amount <= 0:
            flash("Enter an amount greater than 0.")
            return redirect("/dashboard")
    except Exception:
        flash("Invalid amount.")
        return redirect("/dashboard")

    student = get_student(student_id)
    if not student:
        session.clear()
        flash("User not found.")
        return redirect("/")

    # Update balance and save spending record
    student["balance"] = round(student["balance"] - amount, 2)
    update_student(student)

    cursor.execute("INSERT INTO spending (student_id,date,amount) VALUES (?,?,?)",
                   (student_id, today_str(), amount))
    conn.commit()

    # Recompute daily_limit from persisted days_in_plan
    session['daily_limit'] = compute_daily_limit(student["balance"], session.get('days_in_plan', 1))
    return redirect("/dashboard")

@app.route("/topup", methods=["POST"])
def topup():
    student_id = session.get("student_id")
    if not student_id:
        return redirect("/")

    try:
        amount = float(request.form["amount"])
        days = int(request.form["days"])
        if amount <= 0 or days <= 0:
            flash("Amount and days must be positive.")
            return redirect("/dashboard")
    except Exception:
        flash("Invalid top-up data.")
        return redirect("/dashboard")

    student = get_student(student_id)
    if not student:
        session.clear()
        flash("User not found.")
        return redirect("/")

    # Persist new balance and days_in_plan
    student["balance"] = round(student["balance"] + amount, 2)
    student["days_in_plan"] = days
    student["last_day"] = today_str()
    update_student(student)

    session['days_in_plan'] = days
    session['daily_limit'] = compute_daily_limit(student["balance"], days)
    flash("Top-up successful.")
    return redirect("/dashboard")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
@app.route("/forgot", methods=["GET","POST"])
def forgot():
    if request.method == "POST":
        email = request.form["email"]

        cursor.execute("SELECT id FROM students WHERE email=?", (email,))
        user = cursor.fetchone()

        if user:
            import secrets
            token = secrets.token_hex(16)

            cursor.execute(
                "UPDATE students SET reset_token=? WHERE email=?",
                (token,email)
            )
            conn.commit()

            flash(f"Reset link: /reset/{token}")

        else:
            flash("Email not found")

    return render_template("forgot.html")
@app.route("/reset/<token>", methods=["GET","POST"])
def reset(token):

    cursor.execute(
        "SELECT id FROM students WHERE reset_token=?",
        (token,)
    )
    user = cursor.fetchone()

    if not user:
        return "Invalid reset link"

    if request.method == "POST":
        password = request.form["password"]
        hashed = generate_password_hash(password)

        cursor.execute(
            "UPDATE students SET password=?, reset_token=NULL WHERE reset_token=?",
            (hashed, token)
        )
        conn.commit()

        flash("Password updated. Please login.")
        return redirect("/")

    return render_template("reset.html")
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)