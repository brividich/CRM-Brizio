"""Menu Anagrafica a due livelli: nuovo pilastro «Organizzazione», Skill Matrix diventa «Abilitazioni».

Le voci si cercano per destinazione: un'etichetta rinominata da Impostazioni → Navigazione resta
com'è; cambiano solo categoria, gruppo e ordine. Una voce che manca non viene creata.
"""
from django.db import migrations

ORGANIZZAZIONE = "anagrafica:struttura_org"
COMPETENZE = "anagrafica:formazione_dashboard"
PERSONE = "anagrafica:dipendenti_list"

# (destinazione, gruppo, ordine)
VOCI_ORGANIZZAZIONE = (
    ("anagrafica:struttura_org", "Struttura", 180),
    ("anagrafica:esplora_struttura", "Struttura", 181),
    ("anagrafica:organigramma", "Struttura", 182),
    ("anagrafica:prospetti", "Struttura", 183),
    ("anagrafica:mansionario", "Struttura", 184),
    ("anagrafica:aree_list", "Reparti e costi", 186),
    ("anagrafica:centri_costo", "Reparti e costi", 187),
)
ORDINE_ABILITAZIONI = (
    "anagrafica:matrice_competenze", "anagrafica:skill_matrix_macchina", "anagrafica:skm_match_validazione",
    "anagrafica:skm_scadenzario", "anagrafica:skm_refresh", "anagrafica:skm_copertura",
)


def avanti(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    competenze = Cat.objects.filter(landing_url_value=COMPETENZE, is_active=True).order_by("id").first()
    if competenze is None:
        return  # database senza menu (nuova installazione vuota)
    org = Cat.objects.filter(landing_url_value=ORGANIZZAZIONE).order_by("id").first()
    if org is None:
        org = Cat.objects.create(nome="Organizzazione", ordine=150, is_active=True,
                                 landing_url_type="named", landing_url_value=ORGANIZZAZIONE)
    for url, gruppo, ordine in VOCI_ORGANIZZAZIONE:
        Link.objects.filter(url_value=url).update(categoria=org, gruppo=gruppo, ordine=ordine)
    Link.objects.filter(categoria=competenze, gruppo="Skill Matrix").update(gruppo="Abilitazioni")
    for i, url in enumerate(ORDINE_ABILITAZIONI):
        Link.objects.filter(url_value=url).update(categoria=competenze, gruppo="Abilitazioni", ordine=270 + i)


def indietro(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    persone = Cat.objects.filter(landing_url_value=PERSONE, is_active=True).order_by("id").first()
    competenze = Cat.objects.filter(landing_url_value=COMPETENZE, is_active=True).order_by("id").first()
    if persone is None or competenze is None:
        return
    for i, (url, _gruppo, _ordine) in enumerate(VOCI_ORGANIZZAZIONE):
        if url == "anagrafica:mansionario":
            Link.objects.filter(url_value=url).update(categoria=competenze, gruppo="Skill Matrix", ordine=280)
        else:
            Link.objects.filter(url_value=url).update(categoria=persone, gruppo="Organizzazione", ordine=140 + i)
    Link.objects.filter(categoria=competenze, gruppo="Abilitazioni").update(gruppo="Skill Matrix")
    Link.objects.filter(url_value="anagrafica:matrice_competenze").update(gruppo="Trasversale", ordine=270)
    org = Cat.objects.filter(landing_url_value=ORGANIZZAZIONE, nome="Organizzazione").first()
    if org is not None and not Link.objects.filter(categoria=org).exists():
        org.delete()


class Migration(migrations.Migration):
    dependencies = [("anagrafica", "0222_soglie_sovraccarico_impostazioni")]
    operations = [migrations.RunPython(avanti, indietro)]
