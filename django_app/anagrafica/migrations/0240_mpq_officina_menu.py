"""Voce di menu «MOD.176 in officina» in Competenze › Qualifiche, dopo «Processi qualificati». Idempotente.

Il permesso della pagina arriva dal bootstrap ACL (v21, «Sincronizza permessi»).
"""
from django.db import migrations

URL = "anagrafica:mpq_officina"
ETICHETTA = "MOD.176 in officina"


def voce_menu(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    if Link.objects.filter(url_value=URL).exists():
        return
    accanto = Link.objects.filter(url_value="anagrafica:mpq_cruscotto").order_by("-is_active", "id").first()
    if accanto is None:
        return
    # Dopo «Processi qualificati» e dopo le sezioni dedicate (ordine +1, +2…): in coda al gruppo.
    ordine = (Link.objects.filter(gruppo=accanto.gruppo, categoria=accanto.categoria,
                                  url_value__startswith="/anagrafica/mod128/sezione/")
              .order_by("-ordine").values_list("ordine", flat=True).first() or accanto.ordine or 0) + 1
    Link.objects.create(
        url_value=URL, url_type="named", etichetta=ETICHETTA, icona="", gruppo=accanto.gruppo,
        categoria=accanto.categoria, ordine=ordine, active_view_names=URL, is_active=True, is_sistema=False,
    )


def togli(apps, schema_editor):
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value=URL, is_sistema=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0239_sessioni_formative_acl_menu"),
    ]

    operations = [
        migrations.RunPython(voce_menu, togli),
    ]
