"""Voce di menu «Costo orario» in Amministrazione, subito dopo Cedolini (28/10/2026).

Finora la pagina e lo Storico accendevano solo la voce Cedolini (0206, 0208) e
nel menu non c'era un modo diretto di arrivarci. Ora hanno una voce loro; i
loro nomi di vista escono da Cedolini, così si accende una voce sola.
"""
from django.db import migrations

VOCE = "anagrafica:costo_orario"
PAGINE = ["anagrafica:costo_orario", "anagrafica:costo_orario_storico"]
CEDOLINI = "anagrafica:retribuzioni_globale"


def avanti(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    cedolini = Link.objects.filter(url_value=CEDOLINI).order_by("id").first()
    cat = cedolini.categoria if cedolini else Cat.objects.filter(nome="Amministrazione").order_by("id").first()
    if cat is None:
        return
    if not Link.objects.filter(url_value=VOCE).exists():
        Link.objects.create(
            url_value=VOCE, url_type="named", etichetta="Costo orario", icona="", gruppo=cedolini.gruppo if cedolini else "",
            categoria=cat, ordine=(cedolini.ordine + 5) if cedolini else 505,
            active_view_names=",".join(PAGINE), is_active=True, is_sistema=False,
        )
    for link in Link.objects.filter(url_value=CEDOLINI):
        nomi = [n.strip() for n in (link.active_view_names or "").split(",") if n.strip() and n.strip() not in PAGINE]
        link.active_view_names = ",".join(nomi)
        link.save(update_fields=["active_view_names"])


def indietro(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    Link.objects.filter(url_value=VOCE, is_sistema=False).delete()
    for link in Link.objects.filter(url_value=CEDOLINI):
        nomi = [n.strip() for n in (link.active_view_names or "").split(",") if n.strip()]
        nomi += [n for n in PAGINE if n not in nomi]
        link.active_view_names = ",".join(nomi)
        link.save(update_fields=["active_view_names"])


class Migration(migrations.Migration):
    dependencies = [("anagrafica", "0211_competenze_ricalcolo_automatico")]
    operations = [migrations.RunPython(avanti, indietro)]
