import sys
import os
from sqlalchemy import create_engine, text

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings

def clean_db():
    print("Connecting to database...")
    # Ensure DATABASE_URL is string
    db_url = str(settings.DATABASE_URL)
    engine = create_engine(db_url)
    
    script_path = os.path.join(os.path.dirname(__file__), "clean_db.sql")
    print(f"Reading script from {script_path}")
    
    with open(script_path, "r") as f:
        sql_content = f.read()
        
    print("Executing clean_db.sql...")
    try:
        with engine.connect() as connection:
            connection.execute(text(sql_content))
            connection.commit()
        print("Database cleaned successfully.")
    except Exception as e:
        print(f"Error executing script: {e}")
        print("Retrying with direct TRUNCATE command...")
        try:
             with engine.connect() as connection:
                truncate_cmd = """
TRUNCATE TABLE
    shot_characters,
    shots,
    scenes,
    characters,
    creations,
    chapters,
    novels,
    points_records,
    temporary_points,
    points_accounts,
    subscription_points_history,
    creem_payments,
    wechat_payments,
    creem_subscriptions,
    wechat_subscriptions,
    orders,
    subscriptions,
    products,
    webhook_events,
    users
RESTART IDENTITY CASCADE;
"""
                connection.execute(text(truncate_cmd))
                connection.commit()
             print("Database cleaned successfully (fallback).")
        except Exception as e2:
            print(f"Fallback failed: {e2}")

if __name__ == "__main__":
    clean_db()
