"""KPI cliccabili di Admin Portale: ogni tessera porta alla lista filtrata che conta lo stesso numero."""
from __future__ import annotations

import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from admin_portale.tests import _ensure_permessi_table, _ensure_pulsanti_table, _ensure_ruoli_table, _ensure_utenti_table
from core.legacy_models import Pulsante, UtenteLegacy
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    AuditLog,
    Notifica,
    PermissionDefinition,
    RolePermissionGrant,
    RoutePermissionBinding,
)


def _kpi_href(html: str, label: str) -> str:
    for m in re.finditer(r'<a class="[^"]*kpi-link[^"]*" href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        if label in m.group(2):
            return m.group(1).replace("&amp;", "&")
    raise AssertionError(f"KPI cliccabile non trovato: {label}")


class _AdminBase(TestCase):
    def setUp(self):
        _ensure_utenti_table()
        _ensure_ruoli_table()
        _ensure_pulsanti_table()
        _ensure_permessi_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM utenti")
            cursor.execute("DELETE FROM pulsanti")
        self.admin = get_user_model().objects.create_superuser("kpi_admin", "kpi_admin@example.test", "x")
        self.client.force_login(self.admin)
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin KPI", email="kpi_admin@example.test", password="*AD_MANAGED*",
            ruolo="admin", ruolo_id=1, attivo=True, deve_cambiare_password=False,
        )
        for target in ("admin_portale.decorators", "core.context_processors"):
            p1 = patch(f"{target}.get_legacy_user", return_value=self.admin_legacy)
            p2 = patch(f"{target}.is_legacy_admin", return_value=True)
            p1.start()
            p2.start()
            self.addCleanup(p1.stop)
            self.addCleanup(p2.stop)


class IndexKpiTests(_AdminBase):
    def test_utenti_attivi_porta_alla_lista_filtrata(self):
        UtenteLegacy.objects.create(nome="Attivo", email="a@example.test", password="x", attivo=True)
        UtenteLegacy.objects.create(nome="Spento", email="s@example.test", password="x", attivo=False)
        resp = self.client.get(reverse("admin_portale:index"))
        self.assertEqual(resp.status_code, 200)
        href = _kpi_href(resp.content.decode(), "Utenti attivi")
        self.assertEqual(href, reverse("admin_portale:utenti_list") + "?attivo=1")
        lista = self.client.get(href)
        self.assertEqual(lista.context["page_obj"].paginator.count, resp.context["stats"]["utenti_attivi"])
        self.assertEqual(resp.context["stats"]["utenti_attivi"], 2)


class PulsantiKpiTests(_AdminBase):
    def test_pulsanti_attivi_filtra_stessi_pulsanti(self):
        p1 = Pulsante.objects.create(codice="a", nome_visibile="A", modulo="m", url="/a/")
        Pulsante.objects.create(codice="b", nome_visibile="B", modulo="m", url="/b/")
        meta = {p1.id: {"enabled": False}}
        with patch("admin_portale.views._helpers._pulsanti_ui_meta_map", return_value=meta):
            resp = self.client.get(reverse("admin_portale:pulsanti"))
            href = _kpi_href(resp.content.decode(), "Pulsanti attivi")
            self.assertIn("stato=attivi", href)
            lista = self.client.get(href)
        self.assertEqual(resp.context["pulsanti_attivi_count"], 1)
        self.assertEqual(len(lista.context["pulsanti_list"]), resp.context["pulsanti_attivi_count"])


class AclCanonicoKpiTests(_AdminBase):
    def test_code_senza_ruoli_e_binding_senza_grant(self):
        p_ok = PermissionDefinition.objects.create(code="kpi.ok.view", label="ok", module="kpi")
        p_ko = PermissionDefinition.objects.create(code="kpi.ko.view", label="ko", module="kpi")
        RolePermissionGrant.objects.create(legacy_role_id=1, permission=p_ok, enabled=True)
        RoutePermissionBinding.objects.create(permission=p_ok, route_name="kpi:ok", source_app="kpi")
        RoutePermissionBinding.objects.create(permission=p_ko, route_name="kpi:ko", source_app="kpi")
        url = reverse("admin_portale:acl_canonico")
        # Il riepilogo e' globale anche con un filtro attivo sulla pagina.
        resp = self.client.get(url, {"q": "kpi.ok"})
        html = resp.content.decode()
        summary = resp.context["summary"]
        lista = self.client.get(_kpi_href(html, "Code senza ruoli"))
        self.assertEqual(len(lista.context["permission_rows"]), summary["permissions_unassigned"])
        lista = self.client.get(_kpi_href(html, "Binding senza grant"))
        self.assertEqual(len(lista.context["bindings"]), summary["bindings_missing_grant"])
        self.assertGreaterEqual(summary["bindings_missing_grant"], 1)


class LogCenterKpiTests(_AdminBase):
    def test_accessi_conta_solo_login_ok_esatti(self):
        now = timezone.now()
        for azione in ("login_ok", "login_ok", "login_ok_extra", "login_fallito"):
            AuditLog.objects.create(azione=azione, modulo="core", utente_display="Mario", legacy_user_id=7, created_at=now)
        resp = self.client.get(reverse("admin_portale:audit_log"))
        html = resp.content.decode()
        self.assertEqual(resp.context["indicatori"]["accessi"], 2)
        href = _kpi_href(html, "login riusciti")
        self.assertIn("evento=login_ok", href)
        lista = self.client.get(reverse("admin_portale:audit_log") + href)
        self.assertEqual(lista.context["page_obj"].paginator.count, resp.context["indicatori"]["accessi"])


class RuoliPortaleKpiTests(_AdminBase):
    def test_persone_con_ruolo_e_amministratori(self):
        attivo = UtenteLegacy.objects.create(nome="Con ruolo", email="r@example.test", password="x", attivo=True)
        spento = UtenteLegacy.objects.create(nome="Spento", email="sp@example.test", password="x", attivo=False)
        admin_g = AccessGroup.objects.create(code="kpi-admin", label="Admin KPI", priority=90, amministratore=True)
        scaduto_g = AccessGroup.objects.create(code="kpi-old", label="Vecchio", priority=10)
        AccessGroupMembership.objects.create(group=admin_g, legacy_user_id=attivo.id)
        AccessGroupMembership.objects.create(group=admin_g, legacy_user_id=spento.id)
        AccessGroupMembership.objects.create(group=scaduto_g, legacy_user_id=self.admin_legacy.id,
                                             scade_il=timezone.localdate().replace(year=2000))
        url = reverse("admin_portale:ruoli_portale")
        resp = self.client.get(url, {"tab": "sistema"})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertEqual(resp.context["persone_con_ruolo"], 1)
        self.assertEqual(resp.context["amministratori"], 1)
        for label, key in (("persone con almeno un ruolo", "persone_con_ruolo"), ("amministratori da ruolo", "amministratori")):
            lista = self.client.get(_kpi_href(html, label))
            self.assertEqual(lista.context["persone_totale"], resp.context[key], label)


class NotificheConfigKpiTests(_AdminBase):
    def test_tessere_portano_a_hub_notifiche(self):
        Notifica.objects.create(legacy_user_id=1, messaggio="a")
        Notifica.objects.create(legacy_user_id=1, messaggio="b", letta=True, archiviata=True)
        resp = self.client.get(reverse("admin_portale:notifiche_config"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        stats = resp.context["stats"]
        with patch("core.legacy_anagrafica.fetch_anagrafica_rows", return_value=[]):
            for label, key in (("Attive", "attive"), ("di cui non lette", "non_lette"), ("Archiviate", "archiviate")):
                href = _kpi_href(html, label)
                self.assertTrue(href.startswith(reverse("hub_tools:hub_notifiche")))
                lista = self.client.get(href)
                self.assertEqual(lista.context["page_obj"].paginator.count, stats[key], label)


class CentroReportKpiTests(_AdminBase):
    def test_con_dati_personali_filtra_il_catalogo(self):
        url = reverse("admin_portale:centro_report")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        href = _kpi_href(resp.content.decode(), "con dati personali")
        lista = self.client.get(href)
        mostrate = sum(len(g["righe"]) for g in lista.context["gruppi"])
        self.assertEqual(mostrate, resp.context["totale_personali"])
        totale = sum(len(g["righe"]) for g in resp.context["gruppi"])
        self.assertEqual(totale, resp.context["totale_voci"])
