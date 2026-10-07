"""Subnav Anagrafica a cinque pilastri: Persone · Competenze · Salute e sicurezza ·
Amministrazione · Report.

- Persone diviso in gruppi (Dipendenti / Organizzazione / Ingressi) e completato
  con Mansioni. I Ruoli restano in Impostazioni (catalogo unico).
- Competenze: + Scadenzario qualifiche, + Copertura abilitazioni.
- «Compliance» diventa «Salute e sicurezza», in gruppi (Panoramica /
  Sorveglianza sanitaria / Conformità) con le pagine nuove: sessioni di visita, registro referti, libretto sanitario, cambi
  mansione.
- Nuovo pilastro «Report» (atterra su Reportistica) con i report spostati da
  Persone e «Chiedi un report».
- «Dashboard», «Scadenzario» e «Impostazioni» restano voci dirette, invariate.

Categorie e link si cercano per destinazione, non per id: in produzione le voci
possono essere state rinominate da Impostazioni → Navigazione. Un link già
presente cambia solo categoria, gruppo, ordine e visibilità; l'etichetta resta
quella scelta dall'utente. Le voci che l'utente non può aprire restano nascoste
dal filtro ACL della subnav.
"""
from django.db import migrations

PERSONE = ("anagrafica:dipendenti_list", "Persone 👥", 100)
COMPETENZE = ("anagrafica:formazione_dashboard", "Competenze 🎓", 200)
SICUREZZA = ("anagrafica:sicurezza_hub", "Salute e sicurezza", 300)
REPORT = ("anagrafica:reportistica_index", "Report", 600)

# (pilastro, url_value, etichetta, gruppo, ordine, active_view_names extra)
LINKS = [
    (PERSONE, "anagrafica:dipendenti_list", "Elenco dipendenti", "Dipendenti", 100, ""),
    (PERSONE, "anagrafica:dipendente_create", "Nuovo dipendente", "Dipendenti", 105, ""),
    (PERSONE, "anagrafica:ex_dipendenti_list", "Ex dipendenti", "Dipendenti", 110, ""),
    (PERSONE, "anagrafica:documenti_list", "Documenti", "Dipendenti", 115, ""),
    (PERSONE, "anagrafica:organigramma", "Organigramma", "Organizzazione", 140,
     "anagrafica:organigramma_albero,anagrafica:organigramma_diagramma"),
    (PERSONE, "anagrafica:aree_list", "Reparti", "Organizzazione", 145, ""),
    (PERSONE, "anagrafica:mansioni_list", "Mansioni", "Organizzazione", 150, ""),
    (PERSONE, "anagrafica:recruiting_list", "Recruiting", "Ingressi", 170,
     "anagrafica:recruiting_dashboard,anagrafica:recruiting_criteri"),
    (PERSONE, "anagrafica:onboarding_list", "Onboarding", "Ingressi", 175, ""),
    (COMPETENZE, "anagrafica:qualifiche_scadenzario", "Scadenzario qualifiche", "Qualifiche", 262, ""),
    (COMPETENZE, "anagrafica:skm_copertura", "Copertura abilitazioni", "Skill Matrix", 292, ""),
    (SICUREZZA, "anagrafica:sicurezza_hub", "Hub sicurezza", "Panoramica", 300, ""),
    (SICUREZZA, "anagrafica:visite_mediche_dashboard", "Visite mediche", "Sorveglianza sanitaria", 310, ""),
    (SICUREZZA, "anagrafica:visite_mediche_sessioni", "Sessioni di visita", "Sorveglianza sanitaria", 312, ""),
    (SICUREZZA, "anagrafica:referti_coda", "Referti da rivedere", "Sorveglianza sanitaria", 314, ""),
    (SICUREZZA, "anagrafica:referti_registro", "Registro referti", "Sorveglianza sanitaria", 316, ""),
    (SICUREZZA, "anagrafica:libretto_sanitario_generale", "Libretto sanitario", "Sorveglianza sanitaria", 318, ""),
    (SICUREZZA, "anagrafica:conformita_report", "Conformità mansione", "Conformità", 320, ""),
    (SICUREZZA, "anagrafica:cambi_mansione", "Cambi mansione", "Conformità", 325, ""),
    (REPORT, "anagrafica:reportistica_index", "Reportistica", "", 600, ""),
    (REPORT, "anagrafica:reportistica_chat", "Chiedi un report", "", 605,
     "anagrafica:reportistica_chat_scarica"),
    (REPORT, "anagrafica:dipendenti_report", "Report dipendenti", "", 610, ""),
]


def _categoria(Cat, landing, nome, ordine):
    cat = Cat.objects.filter(landing_url_value=landing, is_active=True).order_by("id").first()
    if cat is None:
        cat = Cat.objects.create(nome=nome, ordine=ordine, is_active=True,
                                 landing_url_type="named", landing_url_value=landing)
    return cat


def _attive(existing, url_value, extra):
    nomi = [n.strip() for n in (existing or "").split(",") if n.strip()]
    for n in [url_value] + [e for e in extra.split(",") if e]:
        if n not in nomi:
            nomi.append(n)
    return ",".join(nomi)


def apply(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    sicurezza = Cat.objects.filter(landing_url_value=SICUREZZA[0], is_active=True).order_by("id").first()
    if sicurezza is not None and sicurezza.nome.strip().lower().startswith("compliance"):
        sicurezza.nome = SICUREZZA[1]
        sicurezza.save(update_fields=["nome"])

    cats = {p: _categoria(Cat, *p) for p in (PERSONE, COMPETENZE, SICUREZZA, REPORT)}

    for pilastro, url_value, etichetta, gruppo, ordine, extra in LINKS:
        link = Link.objects.filter(url_value=url_value).order_by("-is_active", "id").first()
        if link is None:
            Link.objects.create(
                categoria=cats[pilastro], etichetta=etichetta, icona="", gruppo=gruppo,
                url_type="named", url_value=url_value, active_view_names=_attive("", url_value, extra),
                ordine=ordine, apri_nuova_tab=False, is_active=True, is_sistema=False,
            )
            continue
        link.categoria = cats[pilastro]
        link.gruppo = gruppo
        link.ordine = ordine
        link.is_active = True
        link.active_view_names = _attive(link.active_view_names, url_value, extra)
        link.save(update_fields=["categoria", "gruppo", "ordine", "is_active", "active_view_names"])


def revert(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    persone = Cat.objects.filter(landing_url_value=PERSONE[0]).order_by("id").first()
    Link.objects.filter(url_value__in=["anagrafica:reportistica_index", "anagrafica:dipendenti_report"]).update(
        categoria=persone, gruppo="")
    Link.objects.filter(url_value="anagrafica:reportistica_chat").delete()
    Cat.objects.filter(landing_url_value=REPORT[0]).delete()
    Cat.objects.filter(landing_url_value=SICUREZZA[0], nome=SICUREZZA[1]).update(nome="Compliance 🛡")


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0135_cambio_mansione_acl"),
    ]

    operations = [
        migrations.RunPython(apply, revert),
    ]
