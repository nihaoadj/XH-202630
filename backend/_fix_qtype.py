"""Fix question_type from single_select to single_choice."""
import sqlite3

db_path = r"c:\Users\qq184\Downloads\XH-202630-dev\XH-202630-dev\backend\data\domain_knowledge.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("UPDATE questionnaire_questions SET question_type = 'single_choice' WHERE question_type = 'single_select'")
print(f"Updated {cur.rowcount} question(s) from single_select -> single_choice")

# Verify
cur.execute("SELECT question_id, question_type FROM questionnaire_questions")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

conn.commit()
conn.close()
print("\nDone!")
