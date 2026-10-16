"""Menu HR senza doppioni (analisi modulo HR, 16/10/2026).

- «Mansioni» (catalogo delle mansioni di rischio) esce da Persone → Organizzazione
  ed entra in Salute e sicurezza, gruppo «Rischi e mansioni»: e' li' che la pagina
  vive (seconda riga della subnav, organigramma rischi, requisiti).
- Un solo nome per il cruscotto della sicurezza: «Cruscotto sicurezza».
- Niente codici MOD.xxx nei nomi di menu: la spiegazione va nel tooltip.

Le etichette cambiano solo se sono ancora quelle di default: una voce rinominata
da Impostazioni → Navigazione resta come l'ha scelta l'utente. Nessun URL cambia.
"""
from django.db import migrations

SICUREZZA_LANDING = "anagrafica:sicurezza_hub"
RINOMINE = {
    "anagrafica:mansioni_list": ("Mansioni", "Mansioni di rischio"),
    "anagrafica:sicurezza_hub": ("Hub sicurezza", "Cruscotto sicurezza"),
    # I codici di modulo escono dalle etichette: restano nel tooltip della voce
    # (anagrafica_extras.GLOSSARIO_MENU) e nelle pagine.
    "anagrafica:mpq_cruscotto": ("Processi qualificati (MOD.128)", "Processi qualificati"),
    "anagrafica:skill_matrix_macchina": ("Abilitazioni macchina (MOD.187)", "Abilitazioni macchina"),
}


def apply(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    sicurezza = Cat.objects.filter(landing_url_value=SICUREZZA_LANDING, is_active=True).order_by("id").first()
    mansioni = Link.objects.filter(url_value="anagrafica:mansioni_list").order_by("-is_active", "id").first()
    if sicurezza is not None and mansioni is not None:
        mansioni.categoria = sicurezza
        mansioni.gruppo = "Rischi e mansioni"
        mansioni.ordine = 330
        mansioni.save(update_fields=["categoria", "gruppo", "ordine"])
    for url_value, (vecchia, nuova) in RINOMINE.items():
        Link.objects.filter(url_value=url_value, etichetta=vecchia).update(etichetta=nuova)


def revert(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    persone = Cat.objects.filter(landing_url_value="anagrafica:dipendenti_list", is_active=True).order_by("id").first()
    if persone is not None:
        Link.objects.filter(url_value="anagrafica:mansioni_list").update(
            categoria=persone, gruppo="Organizzazione", ordine=150)
    for url_value, (vecchia, nuova) in RINOMINE.items():
        Link.objects.filter(url_value=url_value, etichetta=nuova).update(etichetta=vecchia)


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0181_visita_scadenza_medico"),
    ]

    operations = [
        migrations.RunPython(apply, revert),
    ]
