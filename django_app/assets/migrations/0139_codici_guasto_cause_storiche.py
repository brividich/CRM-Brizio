"""Le sei cause storiche di ``WorkOrder.failure_cause`` diventano codici guasto.

Crea sei ``FailureCode`` di tipo CAUSE globali (codice = valore storico in
minuscolo) e collega ``failure_cause_code`` degli interventi che hanno gia' una
causa. Idempotente: i codici si creano solo se mancano, e si collegano solo gli
interventi senza codice. Il CharField ``failure_cause`` non viene toccato.

Reverse: azzera ``failure_cause_code`` sugli interventi (i codici spariscono con
lo schema della 0138 al rollback successivo).
"""

from django.db import migrations

BATCH = 500

CAUSES = [
    ("ELECTRICAL", "Elettrica", 10),
    ("MECHANICAL", "Meccanica", 20),
    ("HYDRAULIC", "Idraulica", 30),
    ("WEAR", "Usura", 40),
    ("OPERATOR_ERROR", "Errore operatore", 50),
    ("OTHER", "Altro", 90),
]


def forwards(apps, schema_editor):
    FailureCode = apps.get_model("assets", "FailureCode")
    WorkOrder = apps.get_model("assets", "WorkOrder")
    created = 0
    by_legacy = {}
    for legacy, label, order in CAUSES:
        code, was_created = FailureCode.objects.get_or_create(
            kind="CAUSE",
            code=legacy.lower(),
            asset_category=None,
            defaults={"label": label, "sort_order": order, "is_active": True},
        )
        created += int(was_created)
        by_legacy[legacy] = code.pk
    linked = 0
    for legacy, code_id in by_legacy.items():
        ids = list(
            WorkOrder.objects.filter(failure_cause=legacy, failure_cause_code__isnull=True)
            .order_by("pk")
            .values_list("pk", flat=True)
            .iterator(chunk_size=BATCH)
        )
        for start in range(0, len(ids), BATCH):
            linked += WorkOrder.objects.filter(pk__in=ids[start:start + BATCH], failure_cause_code__isnull=True).update(
                failure_cause_code_id=code_id
            )
    if created or linked:
        print(f"\n  [assets 0139] Codici causa creati: {created}; interventi collegati: {linked}")


def backwards(apps, schema_editor):
    WorkOrder = apps.get_model("assets", "WorkOrder")
    WorkOrder.objects.filter(failure_cause_code__isnull=False).update(failure_cause_code=None)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0138_codici_guasto"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
