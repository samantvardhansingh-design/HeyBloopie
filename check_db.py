import sqlite3
import json
from python import memory

def main():
    db_path = memory.get_default_db_path()
    print(f"Connecting to database at: {db_path}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, timestamp, user_request, plan_json, status, duration_ms, provider, model FROM tasks ORDER BY id ASC")
    rows = cursor.fetchall()
    
    print(f"\n--- Total tasks recorded in DB: {len(rows)} ---")
    for row in rows:
        print(f"\n[Task ID {row['id']}] - {row['timestamp']}")
        print(f"  User Request: {row['user_request']}")
        print(f"  Status:       {row['status']}")
        print(f"  Duration:     {row['duration_ms']}ms")
        print(f"  Provider:     {row['provider']}")
        print(f"  Model:        {row['model']}")
        plan_summary = "None"
        if row['plan_json']:
            try:
                pj = json.loads(row['plan_json'])
                plan_summary = pj.get('summary', row['plan_json'])
            except Exception:
                plan_summary = row['plan_json']
        print(f"  Plan Summary: {plan_summary}")

    conn.close()

if __name__ == "__main__":
    main()
