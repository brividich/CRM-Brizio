from collections import defaultdict

from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


CODICE_PREPOSTO_PREFIX = "DP"
CODICE_PREPOSTO_PADDING = 4
CODICE_PREPOSTO_START = 0


def _anno_segnalazione(value) -> int:
    if value is None:
        return timezone.localtime(timezone.now()).year
    if timezone.is_naive(value):
        return value.year
    return timezone.localtime(value).year


def _build_codice_preposto(year: int, sequence: int) -> str:
    return f"{CODICE_PREPOSTO_PREFIX}-{year}-{sequence:0{CODICE_PREPOSTO_PADDING}d}"


def _extract_codice_sequence(code: str, year: int) -> int | None:
    prefix = f"{CODICE_PREPOSTO_PREFIX}-{year}-"
    if not code or not str(code).startswith(prefix):
        return None
    try:
        return int(str(code)[len(prefix):])
    except ValueError:
        return None


def populate_codici_identificativi(apps, schema_editor):
    SegnalazionePreposto = apps.get_model("diario_preposto", "SegnalazionePreposto")

    max_sequences = defaultdict(lambda: CODICE_PREPOSTO_START - 1)
    for code, data_segnalazione in SegnalazionePreposto.objects.exclude(
        codice_identificativo=""
    ).values_list("codice_identificativo", "data_segnalazione"):
        year = _anno_segnalazione(data_segnalazione)
        sequence = _extract_codice_sequence(code or "", year)
        if sequence is not None and sequence > max_sequences[year]:
            max_sequences[year] = sequence

    rows = list(
        SegnalazionePreposto.objects.filter(
            Q(codice_identificativo__isnull=True) | Q(codice_identificativo="")
        ).order_by("data_segnalazione", "created_at", "pk")
    )

    for row in rows:
        year = _anno_segnalazione(row.data_segnalazione)
        next_sequence = max_sequences[year] + 1
        max_sequences[year] = next_sequence
        row.codice_identificativo = _build_codice_preposto(year, next_sequence)
        row.save(update_fields=["codice_identificativo"])


class Migration(migrations.Migration):

    dependencies = [
        ("diario_preposto", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="segnalazionepreposto",
            name="codice_identificativo",
            field=models.CharField(blank=True, db_index=True, default="", editable=False, max_length=20),
            preserve_default=False,
        ),
        migrations.RunPython(populate_codici_identificativi, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="segnalazionepreposto",
            name="codice_identificativo",
            field=models.CharField(
                blank=True,
                db_index=True,
                editable=False,
                max_length=20,
                unique=True,
            ),
        ),
    ]
