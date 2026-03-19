from app import get_db

def add_phone_column():
    print("Connecting to the PostgreSQL Ledger...")
    try:
        # Borrow the connection logic you already wrote in app.py
        conn = get_db()
        cur = conn.cursor()
        
        # The SQL Command: Add the column safely. 
        # "IF NOT EXISTS" ensures it doesn't crash if you already created it weeks ago.
        sql_command = "ALTER TABLE students ADD COLUMN IF NOT EXISTS phone VARCHAR(20);"
        
        print("Executing ALTER TABLE command...")
        cur.execute(sql_command)
        
        # Save the changes
        conn.commit()
        
        print("✅ SUCCESS: The 'phone' column has been added to your ledger!")
        
    except Exception as e:
        print(f"❌ Database Error: {e}")
        
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    add_phone_column()