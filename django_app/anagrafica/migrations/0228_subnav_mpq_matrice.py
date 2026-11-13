"""Voce di menu «Matrice processi qualificati» accanto a «Processi qualificati» (Competenze › Qualifiche)."""
from django.db import migrations

URL = "anagrafica:mpq_matrice"


def avanti(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    sorella = Link.objects.filter(url_value="anagrafica:mpq_cruscotto").order_by("id").first()
    if sorella is None or Link.objects.filter(url_value=URL).exists():
        return  # database senza menu o voce già presente
    Link.objects.create(url_value=URL, url_type="named", etichetta="Matrice processi qualificati", icona="",
                        gruppo=sorella.gruppo, categoria=sorella.categoria, ordine=sorella.ordine + 1,
                        active_view_names=URL, is_active=True, is_sistema=False)


def indietro(apps, schema_editor):
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value=URL).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0227_mpq_ruoli_unici"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
