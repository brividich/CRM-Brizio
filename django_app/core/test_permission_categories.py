"""Categorie della pagina Accessi: ogni permesso in un posto leggibile.

Il difetto da cui nascono: raggruppare per "secondo segmento del code" dava un
gruppo per ogni rotta generata dal bootstrap (``Api navigation item create``,
un permesso ciascuno). I code qui sotto sono campioni sintetici con la stessa
forma di quelli del catalogo reale.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from core.permission_categories import (
    CATEGORY_RULES,
    FALLBACK_CATEGORY,
    PLATFORM_MODULE,
    category_for,
    category_order,
    display_module,
    module_label,
    permission_subject,
    readable_label,
)
from core.permission_taxonomy import AREA_ALTRO, area_for_module

# (code, modulo a database, banco atteso, categoria attesa)
CATALOGO_CAMPIONE = [
    ("admin_portale.api_navigation_item_create.view", "admin_portale", "admin_portale", "navigazione"),
    ("admin_portale.utente_toggle_active.view", "admin_portale", "admin_portale", "utenti"),
    ("admin_portale.matrice_permessi.view", "admin_portale", "admin_portale", "accessi"),
    ("admin_portale.api_twofa_policy_save.view", "admin_portale", "admin_portale", "login"),
    ("legacy.admin.gestione_ruoli", "admin", "admin_portale", "accessi"),
    ("admin_portale.automazioni_rule_create.view", "admin_portale", "automazioni", "regole"),
    ("automazioni.automazioni_queue_retry.view", "automazioni", "automazioni", "esecuzioni"),
    ("legacy.assets.assets_wm_map", "assets", "assets", "macchine"),
    ("legacy.assets.assets_wo_close", "assets", "assets", "odl"),
    ("assets.asset_maintenance_rule_override_create.view", "assets", "assets", "manutenzione"),
    ("assets.asset_administrative_deadline_list.view", "assets", "assets", "scadenze"),
    ("legacy.assets.assets_periodic_checks", "assets", "assets", "verifiche"),
    ("legacy.assets.view_assets", "assets", "assets", "inventario"),
    ("anagrafica.fornitore_documento_add.view", "anagrafica", "anagrafica", "fornitori"),
    ("anagrafica.visite.delete", "anagrafica", "anagrafica", "visite"),
    ("legacy.anagrafica.anagrafica_dipendenti", "anagrafica", "anagrafica", "dipendenti"),
    ("api.anomalie_controllo_blocco.manage", "api", "anomalie", "controlli"),
    ("core.route.view", "gestione-anomalie", "anomalie", "segnalazione"),
    ("legacy.dashboard.gestione_anomalie", "dashboard", "anomalie", "gestione"),
    ("legacy.sicurezza.sicurezza_lista", "sicurezza", "rilevazione_incidenti", "rilevazioni"),
    ("legacy.rifiuti.gestione_rentri", "rifiuti", "rentri", "consultazione"),
    ("legacy.rentri.rentri_scarico_eff", "rentri", "rentri", "registro"),
    ("legacy.dpi.dpi_view", "dpi", "dpi", "magazzino"),
    ("dpi.consegna.view", "dpi", "dpi", "gestione"),
    ("login.route.view", "login", PLATFORM_MODULE, "accesso"),
    ("healthz.healthz.view", "healthz", PLATFORM_MODULE, "sonde"),
    ("api.notifiche_popup.manage", "api", PLATFORM_MODULE, "notifiche"),
    ("monitoring_admin.issue_list.view", "monitoring_admin", "monitoring", "issue"),
    ("security.incident_create.view", "security", "security", "incidenti"),
    ("security.admin_config_parsers.view", "security", "security", "configurazione"),
    ("contatori.snmp_dispositivo_verifica_oid.view", "contatori", "contatori", "snmp"),
    ("tasks.kickoff.admin", "tasks", "tasks", "kickoff"),
    ("tickets.api_assegna.view", "tickets", "tickets", "gestione"),
    ("procedure_refresh.my_assignments.view", "procedure_refresh", "procedure_refresh", "mie_procedure"),
]


class DisplayModuleTests(SimpleTestCase):
    def test_banchi_e_categorie_del_catalogo(self):
        for code, module, banco, categoria in CATALOGO_CAMPIONE:
            with self.subTest(code=code):
                self.assertEqual(display_module(code, module), banco)
                self.assertEqual(category_for(code, module)[0], categoria)

    def test_nessun_campione_finisce_in_altre_funzioni(self):
        for code, module, _banco, _categoria in CATALOGO_CAMPIONE:
            with self.subTest(code=code):
                self.assertNotEqual(category_for(code, module)[0], FALLBACK_CATEGORY[0])

    def test_modulo_sconosciuto_resta_visibile(self):
        """L'ignoto non sparisce: banco proprio e categoria di ripiego."""
        self.assertEqual(display_module("nuovo.cosa.view", "nuovo"), "nuovo")
        self.assertEqual(category_for("nuovo.cosa.view", "nuovo"), FALLBACK_CATEGORY)
        self.assertEqual(module_label("nuovo_modulo"), "Nuovo modulo")

    def test_ogni_banco_con_regole_ha_nome_e_area(self):
        for banco in CATEGORY_RULES:
            with self.subTest(banco=banco):
                self.assertNotEqual(area_for_module(banco), AREA_ALTRO)
                self.assertNotIn("_", module_label(banco))

    def test_ordine_delle_categorie_segue_le_regole(self):
        order = category_order("assets")
        self.assertLess(order["manutenzione"], order["inventario"])
        self.assertEqual(order[FALLBACK_CATEGORY[0]], len(order) - 1)

    def test_soggetto_senza_modulo_ne_legacy(self):
        self.assertEqual(permission_subject("legacy.assets.assets_wm_map", "assets"), "wm_map")
        self.assertEqual(
            permission_subject("admin_portale.utente_toggle_active.view", "admin_portale"),
            "utente_toggle_active_view",
        )


class ReadableLabelTests(SimpleTestCase):
    def test_etichetta_scritta_a_mano_resta(self):
        self.assertEqual(readable_label("legacy.assets.asset_create", "assets", "Asset - Nuovo"), "Asset - Nuovo")

    def test_etichetta_tecnica_diventa_leggibile(self):
        label = readable_label(
            "admin_portale.api_navigation_item_create.view",
            "admin_portale",
            "admin_portale / api_navigation_item_create",
        )
        self.assertEqual(label, "Navigazione voce — crea")

    def test_locuzioni_tradotte_insieme(self):
        label = readable_label("assets.work_machine_list.view", "assets", "assets / work_machine_list")
        self.assertEqual(label, "Macchina di lavoro — elenco")

    def test_banco_spostato_non_si_ripete(self):
        label = readable_label(
            "admin_portale.automazioni_queue_retry.view", "admin_portale", "admin_portale / automazioni_queue_retry"
        )
        self.assertEqual(label, "Coda — riprova")

    def test_rotta_senza_nome_usa_il_modulo_d_origine(self):
        self.assertEqual(readable_label("login.route.view", "login", "login"), "Login")
