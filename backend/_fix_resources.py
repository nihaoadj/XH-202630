import sqlite3

db = sqlite3.connect('data/domain_knowledge.db')

# Update resources that have been through review but are unpublished
cursor = db.execute("""
    UPDATE generated_resources 
    SET publication_status = 'published'
    WHERE publication_status = 'unpublished' 
    AND review_status IN ('human_review', 'approved', 'revision_requested', 'pending_review')
""")
print(f"Updated {cursor.rowcount} resources")

# Verify
cursor = db.execute("""
    SELECT review_status, publication_status, COUNT(*) 
    FROM generated_resources 
    GROUP BY review_status, publication_status
""")
print("\nResource status distribution:")
for row in cursor.fetchall():
    print(f"  review={row[0]}, pub={row[1]}, count={row[2]}")

db.commit()
db.close()
