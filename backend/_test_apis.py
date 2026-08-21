import requests, json

# Create session and login
session = requests.Session()
login_resp = session.post('http://127.0.0.1:8000/api/auth/login', json={'username': '111', 'password': '12345678'}, timeout=10)
print('=== Login ===')
print('Status:', login_resp.status_code)

# Test knowledge domains
print('\n=== Knowledge Domains ===')
resp = session.get('http://127.0.0.1:8000/api/knowledge/domains', timeout=10)
print('Status:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    domains = data.get('domains', [])
    print(f'Domains count: {len(domains)}')
    for d in domains:
        print(f'  - {d.get("name", d.get("domain_id"))}: {len(d.get("tracks", []))} tracks')
else:
    print('Error:', resp.text[:500])

# Test profiles list
print('\n=== Profiles ===')
resp = session.get('http://127.0.0.1:8000/api/profiles/', timeout=10)
print('Status:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    items = data.get('items', data.get('profiles', []))
    print(f'Profiles count: {len(items)}')
    for p in items:
        print(f'  - {p.get("learner_id", "")[:30]}... : {p.get("skill_level", "N/A")}')
else:
    print('Error:', resp.text[:500])

# Test generate jobs
print('\n=== Generate Jobs ===')
resp = session.get('http://127.0.0.1:8000/api/generate/jobs', params={'learner_id': 'user_822831763654'}, timeout=10)
print('Status:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    items = data.get('items', data.get('jobs', []))
    print(f'Jobs count: {len(items)}')
    for j in items[:5]:
        print(f'  - {j.get("run_id", "")[:12]}... : status={j.get("job_status")}')
else:
    print('Error:', resp.text[:500])

# Test learning history timeline
print('\n=== Learning History Timeline ===')
resp = session.get('http://127.0.0.1:8000/api/learning-history/user_822831763654/timeline', timeout=10)
print('Status:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print('Keys:', list(data.keys()))
    events = data.get('events', [])
    print(f'Events count: {len(events)}')
    if events:
        print('First event:', json.dumps(events[0], ensure_ascii=False)[:300])
else:
    print('Error:', resp.text[:500])

# Test feedback attempts
print('\n=== Feedback Attempts ===')
resp = session.get('http://127.0.0.1:8000/api/feedback/attempts/user_822831763654', timeout=10)
print('Status:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    items = data.get('items', data.get('attempts', []))
    print(f'Attempts count: {len(items)}')
else:
    print('Error:', resp.text[:500])

# Test resources
print('\n=== Resources ===')
learner_id = 'user_822831763654__rag_engineering_training__8aa198ab9594'
resp = session.get(f'http://127.0.0.1:8000/api/resources/{learner_id}', timeout=10)
print('Status:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print(f'Total: {data.get("total")}')
    for r in data.get('resources', []):
        print(f'  - {r["resource_type"]} (pub={r.get("publication_status")}, review={r.get("review_status")})')

# Test onboarding questions
print('\n=== Onboarding Questions ===')
resp = session.get('http://127.0.0.1:8000/api/onboarding/questions', timeout=10)
print('Status:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print('Keys:', list(data.keys()))
    templates = data.get('templates', data.get('questions', []))
    print(f'Templates/Questions count: {len(templates)}')
else:
    print('Error:', resp.text[:500])
