"""«Da fare» e «Richieste» passano dal pilastro Competenze a Organizzazione.

Accanto a «Formazione» facevano pensare a corsi e attestati: le richieste riguardano chi ha
quale mansione, cioè l'organizzazione. Stesso gruppo «Richieste», dopo «Reparti e costi».
Si spostano solo le voci rimaste dove le ha messe la 0234: una voce già spostata o rinominata
da Impostazioni → Navigazione resta com'è.
"""
from django.db import migrations

VOCI = (("anagrafica:richieste_da_fare", 188), ("anagrafica:richieste", 189))
GRUPPO = "Richieste"
VICINA_NUOVA = ("anagrafica:esplora_struttura", "anagrafica:struttura_org", "anagrafica:aree_list")
VICINA_VECCHIA = ("anagrafica:matrice_competenze", "anagrafica:formazione_dashboard")
ORDINE_VECCHIO = {"anagrafica:richieste_da_fare": 240, "anagrafica:richieste": 241}


def _categoria(Link, Cat, vicine, nome):
    for url in vicine:
        voce = Link.objects.filter(url_value=url).order_by("-is_active", "id").first()
        if voce is not None and voce.categoria_id:
            return voce.categoria
    return Cat.objects.filter(nome=nome).order_by("id").first()


def _sposta(apps, da_vicine, da_nome, a_vicine, a_nome, ordini):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    partenza = _categoria(Link, Cat, da_vicine, da_nome)
    arrivo = _categoria(Link, Cat, a_vicine, a_nome)
    if partenza is None or arrivo is None or partenza.pk == arrivo.pk:
        return
    for url, ordine in ordini.items():
        Link.objects.filter(url_value=url, categoria=partenza, gruppo=GRUPPO).update(categoria=arrivo, ordine=ordine)


def avanti(apps, schema_editor):
    _sposta(apps, VICINA_VECCHIA, "Competenze", VICINA_NUOVA, "Organizzazione", dict(VOCI))


def indietro(apps, schema_editor):
    _sposta(apps, VICINA_NUOVA, "Organizzazione", VICINA_VECCHIA, "Competenze", ORDINE_VECCHIO)


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0234_richieste_competenze_acl_menu"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
