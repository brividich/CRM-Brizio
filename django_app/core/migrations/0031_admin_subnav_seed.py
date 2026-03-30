"""
Migration 0031 — Seed NavigationItem per la subnav interna dell'admin portale.

Converte le voci hardcoded in admin_subnav.html in record DB (section='admin_subnav')
gestibili via Navigation Builder senza toccare codice.
"""
from django.db import migrations


ITEMS = [
    # ── Gruppo "" (nessun separatore prima) ──────────────────────────────────
    dict(
        code="admin-home",
        label="Home Admin",
        group="",
        order=10,
        route_name="admin_portale:index",
        active_patterns="admin_portale:index,admin_portale:home",
        description="Home Admin: panoramica moduli amministrativi. Usa questa pagina come punto di ingresso per utenti, permessi, pulsanti e diagnostica.",
    ),
    # ── Gruppo "accessi" ─────────────────────────────────────────────────────
    dict(
        code="admin-utenti",
        label="Utenti",
        group="accessi",
        order=20,
        route_name="admin_portale:utenti_list",
        active_patterns="admin_portale:utenti_list,admin_portale:utente_edit,admin_portale:utente_permessi_effettivi",
        description="Utenti: cerca e filtra gli utenti legacy/LDAP, assegna ruoli e usa le azioni rapide. Dopo cambio ruolo, consigliato logout/login dell'utente.",
    ),
    dict(
        code="admin-gestione-accessi",
        label="Gestione Accessi",
        group="accessi",
        order=30,
        route_name="admin_portale:gestione_accessi",
        active_patterns="admin_portale:accessi,admin_portale:gestione_accessi",
        description="Gestione Accessi: pagina unificata per configurare tutti i permessi di un ruolo — accordion per modulo con can_view, can_edit, can_delete per ogni pulsante.",
    ),
    dict(
        code="admin-accessi-avanzati",
        label="Accessi Avanzati",
        group="accessi",
        order=40,
        route_name="admin_portale:accessi_avanzati",
        active_patterns="admin_portale:accessi_avanzati,admin_portale:wizard_ruolo",
        description="Accessi Avanzati: dashboard tecnica con indicatori ruoli, override e collegamenti agli strumenti ACL avanzati.",
    ),
    dict(
        code="admin-permessi",
        label="Permessi",
        group="accessi",
        order=50,
        route_name="admin_portale:permessi",
        active_patterns="admin_portale:permessi",
        description="Permessi: matrice ACL per ruolo/modulo/azione. Abilita almeno can_view (o consentito) per rimuovere i 403.",
    ),
    dict(
        code="admin-matrice",
        label="Matrice",
        group="accessi",
        order=60,
        route_name="admin_portale:matrice_permessi",
        active_patterns="admin_portale:matrice_permessi",
        description="Matrice Permessi: scegli un modulo e gestisci can_view per tutti i ruoli in una tabella. Click sull'intestazione colonna per attivare/disattivare un ruolo intero.",
    ),
    dict(
        code="admin-accessi-semplici",
        label="Accessi Semplici",
        group="accessi",
        order=70,
        route_name="admin_portale:accessi_semplice",
        active_patterns="admin_portale:accessi_semplice",
        description="Accessi Semplici: gestione rapida per ruolo in una sola tabella (accesso modulo + pulsanti attivi), senza passaggi tecnici.",
    ),
    # ── Gruppo "navigazione" ─────────────────────────────────────────────────
    dict(
        code="admin-pulsanti",
        label="Pulsanti",
        group="navigazione",
        order=80,
        route_name="admin_portale:pulsanti",
        active_patterns="admin_portale:pulsanti",
        description="Pulsanti: configura menu, link e metadati UI (slot/sezione/ordine). I valori Slot/Sezione guidano topbar e organizzazione del portale.",
    ),
    dict(
        code="admin-topbar-live",
        label="Topbar Live",
        group="navigazione",
        order=90,
        route_name="admin_portale:topbar_live",
        active_patterns="admin_portale:topbar_live",
        description="Topbar Live: editor rapido globale della barra in alto. Modifiche immediate su ordine, visibilità, stato attivo, label e link.",
    ),
    dict(
        code="admin-navigation-builder",
        label="Navigation Builder",
        group="navigazione",
        order=100,
        route_name="admin_portale:navigation_builder",
        active_patterns="admin_portale:navigation_builder",
        description="Navigation Builder: sorgente unica di menu + ruoli + snapshot + redirect legacy. Usa questa pagina per gestire la navigazione senza toccare codice.",
    ),
    # ── Gruppo "automazioni" ─────────────────────────────────────────────────
    dict(
        code="admin-automazioni",
        label="Automazioni",
        group="automazioni",
        order=110,
        route_name="admin_portale:automazioni_rule_list",
        active_patterns=(
            "admin_portale:automazioni_rule_list,admin_portale:automazioni_rule_create,"
            "admin_portale:automazioni_rule_detail,admin_portale:automazioni_rule_edit,"
            "admin_portale:automazioni_sorgenti,admin_portale:automazioni_contenuti,"
            "admin_portale:automazioni_queue_list,admin_portale:automazioni_run_log_list"
        ),
        description="Automazioni / Regole: builder SSR per definire trigger, condizioni in AND, azioni sequenziali e test manuali con pannello campi sempre visibile.",
    ),
    dict(
        code="admin-monitor-errori",
        label="Monitor errori",
        group="automazioni",
        order=120,
        route_name="monitoring_admin:dashboard",
        active_patterns="monitoring_admin:dashboard,monitoring_admin:issue_list,monitoring_admin:issue_detail",
        description="Monitoring: dashboard unificata per issue aperte, criticità recenti, segnalazioni utente e job in anomalia.",
    ),
    dict(
        code="admin-monitor-automazioni",
        label="Monitor automazioni",
        group="automazioni",
        order=130,
        route_name="monitoring_admin:automation_list",
        active_patterns="monitoring_admin:automation_list,monitoring_admin:automation_detail",
        description="Monitor automazioni: stato corrente dei job, fallimenti consecutivi, missing, ritardi e prossima esecuzione attesa.",
    ),
    # ── Gruppo "configurazione" ───────────────────────────────────────────────
    dict(
        code="admin-anagrafica",
        label="Anagrafica",
        group="configurazione",
        order=140,
        route_name="admin_portale:anagrafica_config",
        active_patterns="admin_portale:anagrafica_config",
        description="Anagrafica: configura le liste dropdown (Reparti, Capireparto, Macchine) e i campi extra del profilo dipendente.",
    ),
    dict(
        code="admin-login-config",
        label="Login",
        group="configurazione",
        order=150,
        route_name="admin_portale:login_config",
        active_patterns="admin_portale:login_config",
        description="Login: personalizza titolo, sottotitolo, messaggio di avviso e il bottone SSO della pagina di accesso.",
    ),
    dict(
        code="admin-checklist",
        label="Checklist",
        group="configurazione",
        order=160,
        route_name="admin_portale:checklist_index",
        active_patterns="admin_portale:checklist_index,admin_portale:checklist_utente",
        description="Checklist: gestisci le voci di onboarding (check-in) e offboarding (check-out) e monitora lo stato per ogni dipendente.",
    ),
    # ── Gruppo "sistema" ──────────────────────────────────────────────────────
    dict(
        code="admin-audit-log",
        label="Audit Log",
        group="sistema",
        order=170,
        route_name="admin_portale:audit_log",
        active_patterns="admin_portale:audit_log",
        description="Audit Log: traccia completa delle azioni utenti — filtra per modulo, azione, data. Dettaglio collassabile con payload.",
    ),
    dict(
        code="admin-health-check",
        label="Health Check",
        group="sistema",
        order=180,
        route_name="admin_portale:health_check",
        active_patterns="admin_portale:health_check",
        description="Health Check: stato in tempo reale dei componenti di sistema — database, cache e servizi esterni.",
    ),
    dict(
        code="admin-schema-dati",
        label="Schema Dati",
        group="sistema",
        order=190,
        route_name="admin_portale:schema_dati",
        active_patterns="admin_portale:schema_dati",
        description="Schema Dati: riepilogo tabelle principali (legacy + Django), a cosa servono e dove si gestiscono dal portale.",
    ),
    dict(
        code="admin-acl",
        label="ACL",
        group="sistema",
        order=200,
        route_name="admin_portale:acl_diagnostica",
        active_patterns="admin_portale:acl_diagnostica",
        description="Diagnostica ACL: inserisci un path (es. /assenze/) e opzionalmente un legacy_user_id per vedere match pulsante e record permessi.",
    ),
    dict(
        code="admin-config-srv",
        label="Config SRV",
        group="sistema",
        order=210,
        route_name="admin_portale:ldap_diagnostica",
        active_patterns="admin_portale:ldap_diagnostica",
        description="Config SRV: pannello unico per configurare e testare LDAP / Active Directory e SMTP, con persistenza su config.ini.",
    ),
    # ── Gruppo "hub" ──────────────────────────────────────────────────────────
    dict(
        code="admin-hub-moduli",
        label="Moduli",
        icon="🛠️",
        group="hub",
        order=220,
        route_name="hub_tools:hub_moduli",
        active_patterns="hub_tools:hub_moduli,hub_tools:hub_moduli_toggle",
        description="Hub Moduli: abilita o disabilita i moduli visibili agli utenti. Toggle via AJAX con effetto immediato.",
    ),
    dict(
        code="admin-hub-database",
        label="Database",
        icon="🗄️",
        group="hub",
        order=230,
        route_name="hub_tools:hub_database",
        active_patterns=(
            "hub_tools:hub_database,hub_tools:hub_db_stats,hub_tools:hub_db_backup,"
            "hub_tools:hub_db_cleanup,hub_tools:hub_db_optimize,hub_tools:hub_db_restore"
        ),
        description="DB Manager: statistiche tabelle, backup, pulizia log/sessioni, ottimizzazione e ripristino. Engine rilevato automaticamente.",
    ),
    dict(
        code="admin-hub-builder",
        label="Builder",
        icon="🏠",
        group="hub",
        order=240,
        route_name="hub_tools:hub_homepage_builder",
        active_patterns="hub_tools:hub_homepage_builder",
        description="Homepage Builder: editor visuale per configurare le sezioni della homepage del portale per ruolo.",
    ),
    dict(
        code="admin-hub-wizard",
        label="Wizard",
        icon="⚙️",
        group="hub",
        order=250,
        route_name="hub_tools:hub_setup_wizard",
        active_patterns="hub_tools:hub_setup_wizard",
        description="Setup Wizard: riconfigura il portale modificando database, LDAP, SMTP e altri parametri. I valori mostrati sono quelli attualmente in uso.",
    ),
    dict(
        code="admin-hub-guide",
        label="Guide",
        icon="📚",
        group="hub",
        order=260,
        route_name="hub_tools:hub_guide_list",
        active_patterns="hub_tools:hub_guide_list,hub_tools:hub_guide_view",
        description="Guide e Manuali: documentazione tecnica e guide operative per la gestione del portale.",
    ),
    dict(
        code="admin-hub-notifiche",
        label="Notifiche",
        icon="🔔",
        group="hub",
        order=270,
        route_name="hub_tools:hub_notifiche",
        active_patterns="hub_tools:hub_notifiche,hub_tools:hub_notifica_invia",
        description="Notifiche: monitora, invia e gestisci le notifiche in-app degli utenti.",
    ),
]


def seed_admin_subnav(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    for item in ITEMS:
        NavigationItem.objects.get_or_create(
            code=item["code"],
            defaults=dict(
                label=item["label"],
                section="admin_subnav",
                group=item.get("group", ""),
                order=item.get("order", 100),
                route_name=item.get("route_name", ""),
                url_path=item.get("url_path", ""),
                active_patterns=item.get("active_patterns", ""),
                icon=item.get("icon", ""),
                description=item.get("description", ""),
                is_visible=True,
                is_enabled=True,
            ),
        )


def remove_admin_subnav(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(
        section="admin_subnav",
        code__in=[item["code"] for item in ITEMS],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_notifica_popup_shown"),
    ]

    operations = [
        migrations.RunPython(seed_admin_subnav, reverse_code=remove_admin_subnav),
    ]
