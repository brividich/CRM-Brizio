"""Menu del modulo: le pagine nuove accendono la voce del loro pilastro (27/10/2026).

«Costo orario» sta sotto Amministrazione → Cedolini; «Classificazione e
coefficienti» (e la pagina della persona del Mansionario, che finora non
accendeva niente) sotto Competenze → Mansionario. Come la 0180: si aggiungono
solo nomi di vista alle voci trovate per destinazione, etichette e ordine non
si toccano.
"""
from django.db import migrations

VOCI = [
    ("anagrafica:retribuzioni_globale", ["anagrafica:costo_orario"]),
    ("anagrafica:mansionario", ["anagrafica:mansionario_persona", "anagrafica:mansioni_coefficienti"]),
]


def avanti(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    for url_value, extra in VOCI:
        for link in Link.objects.filter(url_value=url_value):
            nomi = [n.strip() for n in (link.active_view_names or url_value).split(",") if n.strip()]
            nomi += [n for n in extra if n not in nomi]
            link.active_view_names = ",".join(nomi)
            link.save(update_fields=["active_view_names"])


def indietro(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    for url_value, extra in VOCI:
        for link in Link.objects.filter(url_value=url_value):
            nomi = [n.strip() for n in (link.active_view_names or "").split(",") if n.strip() and n.strip() not in extra]
            link.active_view_names = ",".join(nomi)
            link.save(update_fields=["active_view_names"])


class Migration(migrations.Migration):
    dependencies = [("anagrafica", "0205_coefficienti_costo_orario_dati")]
    operations = [migrations.RunPython(avanti, indietro)]
