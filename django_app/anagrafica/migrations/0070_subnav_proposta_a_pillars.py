from django.db import migrations

# Topbar anagrafica — configurazione di partenza «Proposta A» (4 pilastri).
#
# Logica (cfr. docs/anagrafica/LINKS_ANAGRAFICA.md):
#   Dashboard · Scadenzario (unico, filtrabile) · Persone ▾ · Competenze ▾ ·
#   Compliance ▾ · Amministrazione ▾ · ⚙ Impostazioni
#
# Ogni pilastro ha una LANDING (clic sul testo → dashboard del sotto-modulo) e un
# dropdown con gli altri collegamenti. «Competenze» usa il mega-menu a colonne
# (gruppi Formazione / Qualifiche / Trasversale).
#
# La migration è idempotente e opera per ``url_value`` (stabile). I link mancanti
# vengono creati come NON di sistema, così l'utente può riordinarli/eliminarli
# liberamente da Impostazioni → Navigazione. Lo scadenzario resta UNO solo
# (``anagrafica:scadenzario``, già unificato e filtrabile via ``?tipo=``);
# i doppioni e i cataloghi struttura vengono nascosti dalla topbar (non eliminati).

PILLARS = [
    dict(nome="Persone",         icona="👥", ordine=100, landing="anagrafica:dipendenti_list"),
    dict(nome="Competenze",      icona="🎓", ordine=200, landing="anagrafica:formazione_dashboard"),
    dict(nome="Compliance",      icona="🛡", ordine=300, landing="anagrafica:sicurezza_hub"),
    dict(nome="Amministrazione", icona="🪙", ordine=500, landing="anagrafica:retribuzioni_globale"),
]

# (url_value, categoria|None, gruppo, etichetta, ordine)
LINKS = [
    # --- voci dirette ------------------------------------------------------
    ("anagrafica:index",        None, "", "Dashboard",   0),
    ("anagrafica:scadenzario",  None, "", "Scadenzario", 50),
    ("anagrafica:impostazioni", None, "", "⚙️ Impostazioni", 900),
    # --- Persone -----------------------------------------------------------
    ("anagrafica:dipendenti_list",   "Persone", "", "Elenco dipendenti", 100),
    ("anagrafica:dipendente_create", "Persone", "", "Nuovo dipendente",  105),
    ("anagrafica:ex_dipendenti_list","Persone", "", "Ex dipendenti",     110),
    ("anagrafica:organigramma",      "Persone", "", "Organigramma",      115),
    ("anagrafica:onboarding_list",   "Persone", "", "Onboarding",        120),
    ("anagrafica:documenti_list",    "Persone", "", "Documenti",         130),
    ("anagrafica:dipendenti_report", "Persone", "", "Report dipendenti", 140),
    # --- Competenze · Formazione ------------------------------------------
    ("anagrafica:formazione_dashboard",     "Competenze", "Formazione", "Dashboard",     200),
    ("anagrafica:formazione_piani_list",    "Competenze", "Formazione", "Piani formativi",205),
    ("anagrafica:formazione_corsi_list",    "Competenze", "Formazione", "Corsi",         210),
    ("anagrafica:formazione_sessioni_list", "Competenze", "Formazione", "Sessioni",      215),
    ("anagrafica:formazione_istruttori_list","Competenze","Formazione", "Istruttori",    220),
    ("anagrafica:formazione_elearning_hub", "Competenze", "Formazione", "E-learning",    225),
    ("anagrafica:formazione_online_catalog","Competenze", "Formazione", "Corsi online",  230),
    ("anagrafica:formazione_copertura",     "Competenze", "Formazione", "Copertura / gap",235),
    # --- Competenze · Qualifiche ------------------------------------------
    ("anagrafica:qualifiche_dashboard",     "Competenze", "Qualifiche", "Cruscotto",          250),
    ("anagrafica:qualifiche_list",          "Competenze", "Qualifiche", "Catalogo qualifiche",255),
    ("anagrafica:qualifica_sessioni_list",  "Competenze", "Qualifiche", "Sessioni di rinnovo",260),
    # --- Competenze · Trasversale -----------------------------------------
    ("anagrafica:matrice_competenze",       "Competenze", "Trasversale","Matrice competenze", 270),
    # --- Compliance --------------------------------------------------------
    ("anagrafica:sicurezza_hub",            "Compliance", "", "Hub sicurezza",      300),
    ("anagrafica:visite_mediche_dashboard", "Compliance", "", "Visite mediche",     310),
    ("anagrafica:conformita_report",        "Compliance", "", "Conformità mansione",320),
    # --- Amministrazione ---------------------------------------------------
    ("anagrafica:retribuzioni_globale", "Amministrazione", "", "Analisi retribuzioni",500),
    ("anagrafica:retribuzioni_import",  "Amministrazione", "", "Import retribuzioni", 510),
    ("anagrafica:contratti_import",     "Amministrazione", "", "Contratti",           520),
    ("anagrafica:cedolini_import",      "Amministrazione", "", "Cedolini",            530),
    ("anagrafica:ratei_list",           "Amministrazione", "", "Ratei ferie / ROL",   540),
]

# Voci da nascondere dalla topbar (non eliminate): doppioni e cataloghi struttura.
HIDE = [
    "anagrafica:qualifiche_scadenzario",   # → unico Scadenzario
    "anagrafica:mansioni_list",            # catalogo struttura → Impostazioni
    "anagrafica:onboarding_offboarding",   # workflow config → Impostazioni
]


def apply_proposta_a(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    cat_by_name = {}
    for spec in PILLARS:
        cat, _ = Cat.objects.get_or_create(nome=spec["nome"])
        cat.icona = spec["icona"]
        cat.ordine = spec["ordine"]
        cat.is_active = True
        cat.landing_url_type = "named"
        cat.landing_url_value = spec["landing"]
        cat.save()
        cat_by_name[spec["nome"]] = cat

    for url_value, cat_name, gruppo, etichetta, ordine in LINKS:
        cat = cat_by_name.get(cat_name) if cat_name else None
        link = Link.objects.filter(url_value=url_value).order_by("id").first()
        if link is None:
            Link.objects.create(
                url_value=url_value, url_type="named", etichetta=etichetta,
                icona="", gruppo=gruppo, categoria=cat, ordine=ordine,
                active_view_names=url_value, is_active=True, is_sistema=False,
            )
            continue
        link.categoria = cat
        link.gruppo = gruppo
        link.etichetta = etichetta
        link.ordine = ordine
        link.is_active = True
        if not link.active_view_names:
            link.active_view_names = url_value
        link.save()

    for url_value in HIDE:
        Link.objects.filter(url_value=url_value).update(is_active=False)

    # Nasconde le vecchie categorie rimaste senza link attivi (es. «Dipendenti»,
    # «Salute e sicurezza», «Qualifiche»). Robusto rispetto allo stato pregresso.
    pillar_names = {s["nome"] for s in PILLARS}
    for cat in Cat.objects.all():
        if cat.nome in pillar_names:
            continue
        if not cat.links.filter(is_active=True).exists():
            if cat.is_active:
                cat.is_active = False
                cat.save(update_fields=["is_active"])


def noop_reverse(apps, schema_editor):
    """Reverse no-op: la riorganizzazione della topbar resta comunque gestibile
    da Impostazioni → Navigazione. Il rollback dello schema (0069) rimuove i
    campi landing/gruppo; le voci restano e tornano modificabili a mano."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0069_subnav_pillar_landing_gruppo"),
    ]

    operations = [
        migrations.RunPython(apply_proposta_a, noop_reverse),
    ]
