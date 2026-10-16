"""Amministrazione in due pagine: «Cedolini» (retribuzioni) e «Ferie e permessi».

Gli import non hanno più una voce propria: retribuzioni e cedolini sono la
sezione «Importazione» delle due pagine; l'import contratti resta in
Impostazioni → Amministrazione e import. Le voci si cercano per destinazione
(come la 0136); l'etichetta si cambia solo se è ancora quella di serie, così un
nome scelto dall'utente da Impostazioni → Navigazione non si perde.
"""
from django.db import migrations

VOCI = [
    # url_value, etichette di serie, nuova etichetta, viste attive in più
    ("anagrafica:retribuzioni_globale", {"analisi retribuzioni"}, "Cedolini", "anagrafica:retribuzioni_import"),
    ("anagrafica:ratei_list", {"ratei ferie / rol", "ratei ferie/rol"}, "Ferie e permessi", "anagrafica:cedolini_import"),
]
NASCOSTE = ["anagrafica:retribuzioni_import", "anagrafica:cedolini_import", "anagrafica:contratti_import"]


def _attive(existing, extra):
    nomi = [n.strip() for n in (existing or "").split(",") if n.strip()]
    if extra not in nomi:
        nomi.append(extra)
    return ",".join(nomi)


def avanti(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    for url_value, di_serie, etichetta, extra in VOCI:
        for link in Link.objects.filter(url_value=url_value):
            if link.etichetta.strip().casefold() in di_serie:
                link.etichetta = etichetta
            link.active_view_names = _attive(link.active_view_names or url_value, extra)
            link.save(update_fields=["etichetta", "active_view_names"])
    Link.objects.filter(url_value__in=NASCOSTE).update(is_active=False)


def indietro(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    Link.objects.filter(url_value="anagrafica:retribuzioni_globale", etichetta="Cedolini").update(etichetta="Analisi retribuzioni")
    Link.objects.filter(url_value="anagrafica:ratei_list", etichetta="Ferie e permessi").update(etichetta="Ratei ferie / ROL")
    Link.objects.filter(url_value__in=NASCOSTE).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [("anagrafica", "0179_capo_eccezione")]
    operations = [migrations.RunPython(avanti, indietro)]
