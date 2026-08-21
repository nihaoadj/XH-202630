import sqlite3

db = sqlite3.connect('data/domain_knowledge.db')
cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall()]
print('Tables:', tables)

if 'generated_resources' in tables:
    cursor = db.execute('SELECT resource_id, resource_type, publication_status, review_status, learner_id FROM generated_resources ORDER BY created_at DESC LIMIT 20')
    rows = cursor.fetchall()
    print('\nResources in DB:')
    for row in rows:
        rid = str(row[0])[:12]
        print(f'  id={rid}... type={row[1]} pub={row[2]} review={row[3]} learner={str(row[4])[:20] if row[4] else "None"}')
else:
    resource_tables = [t for t in tables if 'resource' in t.lower()]
    print(f'\nResource-related tables: {resource_tables}')
    for table in resource_tables:
        cursor = db.execute(f'SELECT COUNT(*) FROM {table}')
        count = cursor.fetchone()[0]
        print(f'  {table}: {count} rows')

# Check learner_profiles table
if 'learner_profiles' in tables:
    cursor = db.execute('SELECT learner_id, topic, skill_level FROM learner_profiles')
    rows = cursor.fetchall()
    print('\nLearner profiles:')
    for row in rows:
        lid = str(row[0])[:30]
        print(f'  id={lid}... topic={row[1]} level={row[2]}')

db.close()
