"""CN-SGI: sezione dei documenti dal percorso sulla share e uno scaffale per cartella.

Legge solo il database (percorsi già salvati), mai la share.
"""
from django.conf import settings
from django.db import migrations


def avanti(apps, schema_editor):
    from procedure_refresh.libreria import identita_da_cartella, ordine_default, sezione_da_percorso

    ProcedureDocument = apps.get_model("procedure_refresh", "ProcedureDocument")
    ProcedureRevision = apps.get_model("procedure_refresh", "ProcedureRevision")
    SgiScaffale = apps.get_model("procedure_refresh", "SgiScaffale")

    radice = str(getattr(settings, "PROCEDURE_REFRESH_SGI_SHARE_ROOT", "") or "").strip()
    if radice:
        for rev in ProcedureRevision.objects.filter(is_current=True).exclude(source_path=""):
            sez = sezione_da_percorso(rev.source_path, radice)
            if sez:
                ProcedureDocument.objects.filter(pk=rev.document_id).update(sezione=sez)

    esistenti = set(SgiScaffale.objects.values_list("cartella", flat=True))
    cartelle = sorted(
        set(ProcedureDocument.objects.filter(is_active=True).exclude(category="").values_list("category", flat=True))
    )
    for cartella in cartelle:
        if cartella in esistenti:
            continue
        SgiScaffale.objects.create(cartella=cartella[:100], ordine=ordine_default(cartella), **identita_da_cartella(cartella))

    # Rebrand della voce di menu: solo se l'etichetta è ancora uno dei nomi di default
    # (un nome scelto da Navigation Builder resta com'è).
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(
        code="procedure_refresh",
        label__in=["Presa Visione", "Presa visione", "Procedure", "Procedure refresh", "Procedure Refresh"],
    ).update(label="CN-SGI")
    NavigationItem.objects.filter(code="procedure_refresh").update(route_name="procedure_refresh:libreria")


class Migration(migrations.Migration):
    dependencies = [
        ("procedure_refresh", "0011_cn_sgi_libreria"),
        ("core", "0113_tasks_subnav_cruscotto"),
    ]

    operations = [
        migrations.RunPython(avanti, migrations.RunPython.noop),
    ]
