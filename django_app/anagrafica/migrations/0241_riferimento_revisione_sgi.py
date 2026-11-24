"""Riferimenti MOD.128: revisione SGI verificata (``revisione_vista``, ``vista_il``).

I riferimenti già presenti partono dalla revisione in vigore oggi: al deploy nessun falso
«nuova revisione». Abbinamento al registro come ``services/mpq_sgi.documento`` (codice esatto,
poi senza spazi/punti/zeri iniziali, poi codice che comincia così).
"""
import re

from django.db import migrations, models


def _chiave(codice):
    compatto = re.sub(r"[\s.]+", "", (codice or "").upper())
    return re.sub(r"(?<!\d)0+(?=\d)", "", compatto)


def allinea(apps, schema_editor):
    Riferimento = apps.get_model("anagrafica", "RiferimentoProcesso")
    try:
        Revisione = apps.get_model("procedure_refresh", "ProcedureRevision")
    except LookupError:
        return
    correnti = {}
    for rev in Revisione.objects.filter(is_current=True, document__is_active=True).select_related("document"):
        correnti.setdefault(rev.document.code, rev.revision_code or "")
    per_chiave = {}
    for codice, rc in correnti.items():
        per_chiave.setdefault(_chiave(codice), rc)
    for rif in Riferimento.objects.filter(revisione_vista=""):
        k = _chiave(rif.codice)
        rc = per_chiave.get(k)
        if rc is None and len(k) >= 3:
            candidati = sorted((c for c in correnti if _chiave(c).startswith(k)), key=len)
            rc = correnti[candidati[0]] if candidati else None
        if rc:
            rif.revisione_vista = rc
            rif.save(update_fields=["revisione_vista"])


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0240_mpq_officina_menu"),
        ("procedure_refresh", "0016_sgiscaffale_icona_sgiscaffale_logo"),
    ]

    operations = [
        migrations.AddField(
            model_name="riferimentoprocesso", name="revisione_vista",
            field=models.CharField(blank=True, default="", max_length=40, verbose_name="Revisione SGI verificata"),
        ),
        migrations.AddField(
            model_name="riferimentoprocesso", name="vista_il",
            field=models.DateField(blank=True, null=True, verbose_name="Verificata il"),
        ),
        migrations.RunPython(allinea, migrations.RunPython.noop),
    ]
