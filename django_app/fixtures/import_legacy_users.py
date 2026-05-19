"""
Importa ruoli e utenti legacy da legacy_users_export.json in SQL Server PROD.
Uso: python manage.py shell --settings=config.settings.prod < fixtures/import_legacy_users.py
Oppure copiare questo file sul server e eseguirlo direttamente.
"""
import json
from django.db import connections

with open('C:/temp/legacy_users_export.json', encoding='utf-8') as f:
    data = json.load(f)

ruoli = data['ruoli']
utenti = data['utenti']

with connections['default'].cursor() as cur:
    # Ruoli
    for r in ruoli:
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM ruoli WHERE id=%s)
                INSERT INTO ruoli (id, nome)
                VALUES (%s, %s)
            ELSE
                UPDATE ruoli SET nome=%s WHERE id=%s
        """, [r['id'], r['id'], r['nome'], r['nome'], r['id']])
    print(f"Ruoli importati: {len(ruoli)}")

    # Utenti
    inserted = 0
    updated = 0
    for u in utenti:
        cur.execute("SELECT COUNT(1) FROM utenti WHERE id=%s", [u['id']])
        exists = cur.fetchone()[0]
        if exists:
            cur.execute("""
                UPDATE utenti SET nome=%s, email=%s, ruolo_id=%s, attivo=%s
                WHERE id=%s
            """, [u['nome'], u['email'], u.get('ruolo_id'), u.get('attivo', 1), u['id']])
            updated += 1
        else:
            cur.execute("""
                INSERT INTO utenti (id, nome, email, ruolo_id, attivo, password)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, [u['id'], u['nome'], u['email'], u.get('ruolo_id'), u.get('attivo', 1), u.get('password', '')])
            inserted += 1
    print(f"Utenti inseriti: {inserted}, aggiornati: {updated}")

print("Import completato.")
