from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .acl_bootstrap import PERM_AREA, PERM_VIEW, _bootstrap_canonical
from .registry import AREA_PERSONE, AREA_QUALITA, AREE, NORME, ReportParams, all_reports, get_report

User = get_user_model()


def _params(**extra) -> ReportParams:
    today = timezone.localdate()
    return ReportParams(date_from=today - timedelta(days=365), date_to=today, today=today, extra=extra)


class AclBootstrapTest(TestCase):
    def test_crea_permessi_binding_e_menu(self):
        from core.models import NavigationItem, PermissionDefinition, RoutePermissionBinding

        _bootstrap_canonical()
        for code in [PERM_VIEW, *PERM_AREA.values()]:
            self.assertTrue(PermissionDefinition.objects.filter(code=code).exists(), code)
        for route in ("report_conformita:index", "report_conformita:report", "report_conformita:riesame"):
            self.assertTrue(
                RoutePermissionBinding.objects.filter(route_name=route, permission_id=PERM_VIEW).exists(), route
            )
        nav = NavigationItem.objects.get(code="report-conformita")
        self.assertEqual(nav.required_permission_code, PERM_VIEW)

    def test_idempotente(self):
        from core.models import RoutePermissionBinding

        _bootstrap_canonical()
        _bootstrap_canonical()
        self.assertEqual(RoutePermissionBinding.objects.filter(route_name="report_conformita:report").count(), 1)

    def test_ogni_area_ha_un_permesso(self):
        self.assertEqual(set(PERM_AREA), set(AREE))


class RegistryTest(TestCase):
    def test_report_registrati_e_coerenti(self):
        reports = all_reports()
        self.assertGreaterEqual(len(reports), 15)
        slugs = [r.slug for r in reports]
        self.assertEqual(len(slugs), len(set(slugs)))
        for r in reports:
            self.assertIn(r.area, AREE, r.slug)
            self.assertTrue(r.clausole, r.slug)
            self.assertTrue(set(r.norme) <= set(NORME), r.slug)

    def test_tutte_le_norme_coperte(self):
        coperte = {n for r in all_reports() for n in r.norme}
        self.assertEqual(coperte, set(NORME))

    def test_parametri_periodo_invertito_e_filtro_non_ammesso(self):
        report = get_report("registro-nc-ofi")
        params = ReportParams.from_querydict(
            {"da": "2026-06-30", "a": "2026-01-01", "norma": "iniezione"}, filtri=report.filtri
        )
        self.assertEqual(params.date_from, date(2026, 1, 1))
        self.assertEqual(params.date_to, date(2026, 6, 30))
        self.assertEqual(params.extra, {})

    def test_ogni_report_si_calcola_su_db_vuoto(self):
        for r in all_reports():
            with self.subTest(report=r.slug):
                result = r.build(_params())
                self.assertTrue(result.kpis)
                self.assertTrue(result.columns)
                self.assertEqual(len(result.rows), len(result.row_tones))


class ReportDatiSinteticiTest(TestCase):
    def test_nc_in_ritardo_e_filtro_norma(self):
        from gestione_specifiche.models import RegistroOFI

        oggi = timezone.localdate()
        RegistroOFI.objects.create(
            numero=9001, data_apertura=oggi - timedelta(days=40), tipo=RegistroOFI.TIPO_NC,
            data_richiesta=oggi - timedelta(days=5), norma_iso45001=True, opportunita="Sintetico",
        )
        RegistroOFI.objects.create(numero=9002, data_apertura=oggi - timedelta(days=10), opportunita="Altro")
        result = get_report("registro-nc-ofi").build(_params())
        kpi = {k.label: k.value for k in result.kpis}
        self.assertEqual(kpi["Aperte"], 2)
        self.assertEqual(kpi["Oltre la data di chiusura"], 1)
        self.assertIn("danger", result.row_tones)

        filtrato = get_report("registro-nc-ofi").build(_params(norma="45001"))
        self.assertEqual(len(filtrato.rows), 1)

    def test_fornitore_insufficiente_e_mai_valutato(self):
        from anagrafica.models import Fornitore, FornitoreValutazione

        f1 = Fornitore.objects.create(ragione_sociale="Fornitore Alfa")
        Fornitore.objects.create(ragione_sociale="Fornitore Beta")
        FornitoreValutazione.objects.create(fornitore=f1, qualita=2, puntualita=2, comunicazione=3)
        result = get_report("albo-fornitori").build(_params())
        esiti = {row[0]: row[-1] for row in result.rows}
        self.assertEqual(esiti["Fornitore Alfa"], "Insufficiente")
        self.assertEqual(esiti["Fornitore Beta"], "Mai valutato")

    def test_verifica_scaduta(self):
        from assets.models import PeriodicVerification

        PeriodicVerification.objects.create(
            name="Taratura calibro", next_verification_date=timezone.localdate() - timedelta(days=3)
        )
        result = get_report("verifiche-periodiche").build(_params())
        self.assertEqual(result.row_tones, ["danger"])

    def test_eventi_senza_nominativo(self):
        from rilevazione_incidenti.models import RilevazioneIncidente

        RilevazioneIncidente.objects.create(
            nominativo="Persona Sintetica", tipologia_scheda="Near Miss", tipo_evento="near_miss",
            data_segnalazione=timezone.now(), reparto="Officina",
        )
        RilevazioneIncidente.objects.create(
            nominativo="Persona Sintetica", tipologia_scheda="Accident", tipo_evento="incidente",
            data_segnalazione=timezone.now() - timedelta(days=10), chiusura_rspp=True,
            data_chiusura_rspp=timezone.localdate() - timedelta(days=4),
        )
        result = get_report("eventi-sicurezza").build(_params())
        self.assertEqual(len(result.rows), 2)
        for row in result.rows:
            self.assertNotIn("Persona Sintetica", " ".join(str(v) for v in row))
        kpi = {k.label: k.value for k in result.kpis}
        self.assertEqual(kpi["Giorni medi di chiusura"], 6)


class ReportViewsTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="rc_admin", password="x", is_superuser=True, is_staff=True)

    def test_anonimo_rimandato_al_login(self):
        resp = self.client.get(reverse("report_conformita:index"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp.url.lower())

    def test_utente_senza_permessi_non_vede_nulla(self):
        utente = User.objects.create_user(username="rc_nessuno", password="x")
        self.client.force_login(utente)
        resp = self.client.get(reverse("report_conformita:report", args=["revisione-accessi"]))
        self.assertNotEqual(resp.status_code, 200)

    def test_index_e_tutti_i_report_a_video(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("report_conformita:index"))
        self.assertEqual(resp.status_code, 200)
        for r in all_reports():
            self.assertContains(resp, reverse("report_conformita:report", args=[r.slug]))
            with self.subTest(report=r.slug):
                page = self.client.get(reverse("report_conformita:report", args=[r.slug]))
                self.assertEqual(page.status_code, 200)
                self.assertNotContains(page, "{#")

    def test_report_inesistente_404(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("report_conformita:report", args=["non-esiste"]))
        self.assertEqual(resp.status_code, 404)

    def test_download_pdf_xlsx_tracciati(self):
        from core.models import AuditLog

        self.client.force_login(self.admin)
        url = reverse("report_conformita:report", args=["albo-fornitori"])
        pdf = self.client.get(url, {"formato": "pdf"})
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        xlsx = self.client.get(url, {"formato": "xlsx"})
        self.assertTrue(xlsx.content.startswith(b"PK"))
        self.assertEqual(
            AuditLog.objects.filter(azione="report_conformita_download", modulo="report_conformita").count(), 2
        )

    def test_tutti_i_pdf_si_generano(self):
        self.client.force_login(self.admin)
        for r in all_reports():
            with self.subTest(report=r.slug):
                resp = self.client.get(reverse("report_conformita:report", args=[r.slug]), {"formato": "pdf"})
                self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_riesame_web_e_pdf(self):
        self.client.force_login(self.admin)
        url = reverse("report_conformita:riesame")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Riesame della direzione")
        pdf = self.client.get(url, {"formato": "pdf"})
        self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_permesso_di_area_fail_closed(self):
        consentiti = {PERM_VIEW, PERM_AREA[AREA_QUALITA]}
        self.client.force_login(self.admin)
        with patch("report_conformita.views._has_perm", side_effect=lambda req, code: code in consentiti):
            index = self.client.get(reverse("report_conformita:index"))
            self.assertContains(index, reverse("report_conformita:report", args=["albo-fornitori"]))
            self.assertNotContains(index, reverse("report_conformita:report", args=["competenze"]))
            negato = self.client.get(reverse("report_conformita:report", args=["competenze"]))
            self.assertEqual(negato.status_code, 302)
            riesame = self.client.get(reverse("report_conformita:riesame"))
            self.assertNotContains(riesame, get_report("competenze").title)
            self.assertEqual(get_report("competenze").area, AREA_PERSONE)
