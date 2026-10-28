"""core 0102: ogni pagina «Impostazioni» si apre solo con l'azione «impostazioni» della matrice.

Dati sintetici: ruoli e permessi si creano nel test.
"""
from __future__ import annotations

import importlib
import re
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from core.acl_v2 import _find_canonical_binding
from core.models import (
    AccessGroup,
    GroupPermissionGrant,
    PermissionDefinition,
    RoutePermissionBinding,
    RuoloPermessoModulo,
)
from core.permessi.impostazioni import AZIONE_IMPOSTAZIONI, IMPOSTAZIONI
from core.permessi.sync import codici_desiderati

migrazione = importlib.import_module("core.migrations.0102_impostazioni_tutte_le_pagine")
SOC = IMPOSTAZIONI["soc"].codici

# Pagine con «impostazioni/configurazione» nel percorso che NON sono impostazioni di un
# modulo, col motivo. Una pagina nuova di impostazioni va nella tabella, non qui.
ESCLUSE = {
    "anagrafica:rettifiche": "coda di lavoro HR (richieste GDPR art. 16), non configurazione",
    "anagrafica:sicurezza_operativa_config": "salvataggio di un riquadro della pagina Mansioni di rischio",
    "gestione_carichi_macchina:macchina_config": "configurazione della macchina dal Gantt del piano",
    "procedure_refresh:admin_dashboard": "e' tutta la gestione delle campagne di presa visione",
    "notifiche_impostazioni": "preferenze personali delle notifiche",
    "automazioni:automazioni_api_table_config_list": "API del designer delle regole",
    "automazioni:automazioni_api_table_config_save": "API del designer delle regole",
    "automazioni:automazioni_api_table_config_delete": "API del designer delle regole",
    "assets:api_dashboard_save_config": "disposizione personale della dashboard",
    "assets:assets_meters_api:ingest_config": "API dei dispositivi di lettura contatori",
    "api_employee_board_widget_config": "disposizione personale della bacheca",
    "api_anomalie_controllo_impostazioni": "impostazioni del singolo controllo, nella pagina della segnalazione",
}
# Moduli interi di amministrazione (solo amministratore) o tecnici: fuori dalla tabella.
PREFISSI_ESCLUSI = ("admin_portale:", "admin:", "hub_tools:", "setup_wizard:", "monitoring_admin:")
# Rotte SOC con permesso proprio per nome rotta: il permesso deve stare fra i codici del SOC.
SOC_ROTTE = {
    "soc_settings": "security.soc_settings.view", "soc_settings_run": "security.soc_settings.run",
    "watchguard_credenziali": "security.watchguard_credenziali.view",
    "veeam_credenziali": "security.veeam_credenziali.view", "letture": "security.letture.view",
    "battito": "security.battito.view", "lettura_esegui": "security.lettura_esegui.view",
    "admin_config_general": "security.config_general.view", "admin_config_sources": "security.config_sources.view",
    "admin_config_parsers": "security.config_parsers.view", "admin_config_alert_rules": "security.config_alert.view",
    "admin_config_suppressions": "security.config_suppressions.view",
    "admin_config_backups": "security.config_backups.view",
    "admin_config_notifications": "security.config_notifications.view",
    "admin_config_ticketing": "security.config_ticketing.view", "admin_config_audit": "security.config_audit.view",
    "automation": "security.automation.view", "automation_simulate": "security.automation_simulate.view",
    "automation_toggle": "security.automation.manage", "inventory": "security.inventory.view",
    "inventory_map": "security.inventory_map.view", "inventory_discard": "security.inventory_discard.view",
    "software_mapping": "security.software_mapping.view", "admin_autoconfig": "security.autoconfig.view",
    "admin_autoconfig_apply": "security.autoconfig_apply.view", "admin_autoconfig_fix": "security.autoconfig_fix.view",
}


# Rotte che hanno gia' un permesso tutto loro, elencato fra i codici del modulo.
CODICE_DELLA_ROTTA = {
    "assets:gestione_admin": ("assets", "assets.gestione_admin.view"),
    "automazioni:automazioni_settings": ("automazioni", "automazioni.automazioni_settings.view"),
}


def _rotte():
    def giro(res, prefisso="", ns=""):
        for p in res.url_patterns:
            if isinstance(p, URLResolver):
                nns = f"{ns}:{p.namespace}" if ns and p.namespace else (p.namespace or ns)
                yield from giro(p, prefisso + str(p.pattern), nns)
            elif isinstance(p, URLPattern) and p.name:
                yield prefisso + str(p.pattern), (f"{ns}:{p.name}" if ns else p.name)
    return list(giro(get_resolver()))


class CoperturaTests(TestCase):
    def test_ogni_pagina_impostazioni_e_nella_tabella(self):
        coperte = {r for p in IMPOSTAZIONI.values() for r in p.rotte}
        mancanti = []
        for percorso, nome in _rotte():
            if not re.search(r"impostazion|configurazion|/config/|config/$", percorso):
                continue
            if nome in coperte or nome in ESCLUSE or nome.startswith(PREFISSI_ESCLUSI):
                continue
            modulo_codice = CODICE_DELLA_ROTTA.get(nome)
            if modulo_codice and modulo_codice[1] in IMPOSTAZIONI[modulo_codice[0]].codici:
                continue
            if nome.startswith("security:"):
                code = SOC_ROTTE.get(nome.split(":", 1)[1])
                if code in SOC:
                    continue
            mancanti.append(f"{nome} ({percorso})")
        self.assertEqual(mancanti, [], "Pagine di impostazioni fuori dalla tabella core/permessi/impostazioni.py")

    def test_codici_soc_della_tabella(self):
        for rotta, code in SOC_ROTTE.items():
            self.assertIn(code, SOC, rotta)
        # Il permesso della gestione operativa resta a «gestire».
        self.assertNotIn("security.config.view", SOC)


class Migrazione0102Tests(TestCase):
    def setUp(self):
        cache.clear()
        for principale, _nuovo, modulo, _rotte in migrazione.ROTTE:
            PermissionDefinition.objects.get_or_create(code=principale, defaults={"label": principale, "module": modulo})
        for code in (*SOC, "security.config.view", "anagrafica.skillmatrix.manage"):
            PermissionDefinition.objects.get_or_create(code=code, defaults={"label": code, "module": "security"})
        RoutePermissionBinding.objects.update_or_create(
            route_name="anagrafica:skm_impostazioni", path_pattern="",
            defaults={"permission_id": "anagrafica.skillmatrix.manage", "match_strategy": "exact", "is_active": True},
        )
        RoutePermissionBinding.objects.update_or_create(
            route_name="security:admin_config", path_pattern="",
            defaults={"permission_id": "security.config.view", "match_strategy": "exact", "is_active": True},
        )
        self.gestore = AccessGroup.objects.create(code="t-soc-g", label="Gestore SOC (test)", priority=300)
        self.lettore = AccessGroup.objects.create(code="t-soc-l", label="Lettore SOC (test)", priority=200)
        RuoloPermessoModulo.objects.create(ruolo=self.gestore, modulo="soc", azione="gestire", ambito="tutti")
        RuoloPermessoModulo.objects.create(ruolo=self.lettore, modulo="soc", azione="vedere", ambito="tutti")
        for ruolo in (self.gestore, self.lettore):
            GroupPermissionGrant.objects.create(
                group=ruolo, permission_id="security.config.view", enabled=True, note="matrice ruoli"
            )

    def test_tabella_e_migrazione_allineate(self):
        for principale, _nuovo, _modulo, rotte in migrazione.ROTTE:
            for rotta in rotte:
                moduli = [k for k, p in IMPOSTAZIONI.items() if rotta in p.rotte]
                self.assertEqual(len(moduli), 1, rotta)
                self.assertEqual(IMPOSTAZIONI[moduli[0]].codici[0], principale, rotta)
        self.assertEqual(migrazione.SOC_CODICI, SOC)

    def test_rotte_legate_al_permesso_delle_impostazioni(self):
        migrazione.avanti(django_apps, None)
        for principale, _nuovo, _modulo, rotte in migrazione.ROTTE:
            for rotta in rotte:
                percorso = reverse(rotta, kwargs=_kwargs(rotta))
                binding, come = _find_canonical_binding(route_name=rotta, path_norm=percorso.lower())
                self.assertEqual((binding.permission_id, come), (principale, "route_name"), rotta)

    def test_soc_gestire_copiato_su_impostazioni(self):
        migrazione.avanti(django_apps, None)
        migrazione.avanti(django_apps, None)  # idempotente
        celle = RuoloPermessoModulo.objects.filter(
            modulo="soc", azione=AZIONE_IMPOSTAZIONI, ruolo__in=(self.gestore, self.lettore)
        )
        self.assertEqual(list(celle.values_list("ruolo_id", flat=True)), [self.gestore.id])
        codici = set(GroupPermissionGrant.objects.filter(group=self.gestore).values_list("permission_id", flat=True))
        self.assertTrue(set(SOC) <= codici)
        self.assertFalse(GroupPermissionGrant.objects.filter(group=self.lettore, permission_id__in=SOC).exists())


def _kwargs(rotta):
    if rotta.endswith(("categoria_modifica", "categoria_elimina", "evento_detail", "evento_chiudi", "evento_riapri",
                       "proposta_decidi")):
        return {"pk": 1}
    if rotta.endswith("voce_nuova"):
        return {"evento_pk": 1}
    if rotta.endswith("voce_modifica"):
        return {"evento_pk": 1, "pk": 1}
    if rotta.endswith("elearning_regola_corso"):
        return {"corso_id": 1}
    return {}


class MatriceSocTests(TestCase):
    def setUp(self):
        cache.clear()
        for code in (*SOC, "security.config.view"):
            PermissionDefinition.objects.get_or_create(code=code, defaults={"label": code, "module": "security"})
        self.ruolo = AccessGroup.objects.create(code="t-soc", label="SOC (test)", priority=300)

    def _cella(self, azione):
        RuoloPermessoModulo.objects.create(ruolo=self.ruolo, modulo="soc", azione=azione, ambito="tutti")

    def test_gestire_non_apre_le_impostazioni_ma_tiene_la_gestione(self):
        self._cella("gestire")
        desiderati, _ = codici_desiderati(self.ruolo)
        self.assertFalse(set(SOC) & desiderati)

    def test_impostazioni_apre_tutte_le_pagine(self):
        self._cella(AZIONE_IMPOSTAZIONI)
        desiderati, _ = codici_desiderati(self.ruolo)
        self.assertTrue(set(SOC) <= desiderati)
        self.assertNotIn("security.config.view", desiderati)


class GateSocTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/soc/impostazioni/")
        self.request.user = get_user_model().objects.create_user(username="t.soc.imp", password="x")

    def test_sistema_acceso_decide_l_azione_impostazioni(self):
        from security.services.configuration import can_configure_soc

        with mock.patch("core.permessi.motore.sistema_ruoli_attivo", return_value=True), \
                mock.patch("security.services.configuration.can_manage_security_config", return_value=True), \
                mock.patch("core.acl_v2.request_has_permission_code", return_value=False):
            self.assertFalse(can_configure_soc(self.request))
        with mock.patch("core.permessi.motore.sistema_ruoli_attivo", return_value=True), \
                mock.patch("security.services.configuration.can_manage_security_config", return_value=False), \
                mock.patch("core.acl_v2.request_has_permission_code", side_effect=lambda r, c: c == SOC[0]):
            self.assertTrue(can_configure_soc(self.request))

    def test_sistema_spento_resta_il_permesso_di_configurazione(self):
        from security.services.configuration import can_configure_soc

        with mock.patch("core.permessi.motore.sistema_ruoli_attivo", return_value=False), \
                mock.patch("security.services.configuration.can_manage_security_config", return_value=True):
            self.assertTrue(can_configure_soc(self.request))
