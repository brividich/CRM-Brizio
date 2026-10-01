from django.db import migrations

FAILED = "failed"
SKIPPED = "skipped"


def repair_skipped_status(apps, schema_editor):
    """Mail e file scartati (nessun parser li riconosce) erano stati salvati come FALLITI.

    Il motivo dello scarto e' nel `raw_payload` (`skip_reason`); un vero errore di parser ha
    invece `parser_error`. Si corregge in Python (senza filtri JSON, che su SQL Server sono
    fragili) e solo dove c'e' il motivo dello scarto e non c'e' un errore.
    """
    for model_name in ("SecurityMailboxMessage", "SecuritySourceFile"):
        Model = apps.get_model("security", model_name)
        for row in Model.objects.filter(parse_status=FAILED).iterator():
            payload = row.raw_payload or {}
            # Le mail hanno anche l'esito della pipeline: «skipped» = nessun parser.
            pipeline = getattr(row, "pipeline_result", None) or {}
            was_skipped = bool(payload.get("skip_reason")) or pipeline.get("status") == "skipped"
            if was_skipped and not payload.get("parser_error"):
                Model.objects.filter(pk=row.pk).update(parse_status=SKIPPED)


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0013_securityvpnaccess_kind_reason"),
    ]

    operations = [
        migrations.RunPython(repair_skipped_status, migrations.RunPython.noop),
    ]
