from django.db import migrations


def backfill_richiedente_user(apps, schema_editor):
    """
    Collega i ticket esistenti all'utente Django corrispondente usando la catena:
    richiedente_legacy_user_id → anagrafica_dipendenti.utente_id → aliasusername → auth_user.username
    """
    db_alias = schema_editor.connection.alias
    conn = schema_editor.connection

    # Costruisce il mapping legacy_user_id → django user_id in una sola query
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT ad.utente_id, au.id
            FROM anagrafica_dipendenti ad
            INNER JOIN auth_user au ON au.username = ad.aliasusername
            WHERE ad.utente_id IS NOT NULL
              AND ad.aliasusername IS NOT NULL
              AND ad.aliasusername <> ''
        """)
        legacy_to_user = dict(cursor.fetchall())

    if not legacy_to_user:
        return

    Ticket = apps.get_model("tickets", "Ticket")
    batch = []
    qs = (
        Ticket.objects.using(db_alias)
        .filter(richiedente_user__isnull=True, richiedente_legacy_user_id__isnull=False)
    )
    for ticket in qs.iterator(chunk_size=500):
        user_id = legacy_to_user.get(ticket.richiedente_legacy_user_id)
        if user_id:
            ticket.richiedente_user_id = user_id
            batch.append(ticket)

    if batch:
        Ticket.objects.using(db_alias).bulk_update(batch, ["richiedente_user_id"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0010_richiedente_user_fk"),
    ]

    operations = [
        migrations.RunPython(backfill_richiedente_user, reverse_code=migrations.RunPython.noop),
    ]
