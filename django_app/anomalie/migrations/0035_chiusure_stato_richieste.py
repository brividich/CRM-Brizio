"""Storico delle chiusure (chiusura_service, 26/11/2026).

- Richieste di informazioni ancora aperte su anomalie chiuse: chiuse con la nota
  «Chiusa con l'anomalia».
- Anomalie chiuse con stato «In attesa» (o vuoto): riprendono l'ultima decisione
  presa dal registro attività; senza decisioni restano come sono.

Solo dati, nessuno schema. Senza la tabella legacy ``anomalie`` non fa nulla.
"""
from django.db import migrations
from django.utils import timezone

NOTA = "Chiusa con l'anomalia: nessuna risposta registrata."
NON_DECISIONI = {"", "in attesa", "chiusa", "torna alla qualità", "decisione qualità", "in attesa chiarimenti"}
LIBERI = {"", "in attesa"}


def avanti(apps, schema_editor):
    conn = schema_editor.connection
    if "anomalie" not in conn.introspection.table_names():
        return
    with conn.cursor() as cur:
        cur.execute("SELECT id, avanzamento FROM anomalie WHERE COALESCE(chiudere, 0) = 1")
        chiuse = {int(r[0]): str(r[1] or "").strip() for r in cur.fetchall()}
    if not chiuse:
        return
    Richiesta = apps.get_model("anomalie", "AnomaliaRichiestaInfo")
    Log = apps.get_model("anomalie", "AnomaliaActionLog")
    ids = sorted(chiuse)
    adesso = timezone.now()
    for i in range(0, len(ids), 500):
        Richiesta.objects.filter(anomalia_id__in=ids[i:i + 500], risposta_il__isnull=True).update(
            risposta=NOTA, risposta_da_display="Sistema (chiusure)", risposta_ruolo="chiusura", risposta_il=adesso,
        )
    for aid, av in chiuse.items():
        if av.lower() not in LIBERI:
            continue
        stato = ""
        for s in (Log.objects.filter(anomalia_id=aid).exclude(new_status="").order_by("-id")
                  .values_list("new_status", flat=True)[:200]):
            if str(s or "").strip().lower() not in NON_DECISIONI:
                stato = str(s).strip()[:255]
                break
        if stato:
            with conn.cursor() as cur:
                cur.execute("UPDATE anomalie SET avanzamento = %s WHERE id = %s AND COALESCE(chiudere, 0) = 1",
                            [stato, aid])


class Migration(migrations.Migration):
    dependencies = [("anomalie", "0034_nominativi_cognome_nome")]
    operations = [migrations.RunPython(avanti, migrations.RunPython.noop)]
