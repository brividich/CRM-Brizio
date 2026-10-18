"""Centro report: catalogo, registro emissioni, profili di layout, pagina admin."""
from __future__ import annotations

import hashlib
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import FileResponse, HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from core.models import ReportAssegnazioneLayout, ReportEmissione, ReportProfiloLayout, SiteConfig
from core.report_centro import catalogo, layout, registro

User = get_user_model()


def _nomi_route(patterns=None, namespace="") -> set[str]:
    nomi: set[str] = set()
    for p in patterns if patterns is not None else get_resolver().url_patterns:
        if isinstance(p, URLResolver):
            ns = f"{namespace}{p.namespace}:" if p.namespace else namespace
            nomi |= _nomi_route(p.url_patterns, ns)
        elif isinstance(p, URLPattern) and p.name:
            nomi.add(f"{namespace}{p.name}")
    return nomi


class CatalogoTests(SimpleTestCase):
    def test_chiavi_uniche_e_valori_ammessi(self):
        chiavi = [v.chiave for v in catalogo.voci()]
        self.assertEqual(len(chiavi), len(set(chiavi)))
        self.assertGreater(len(chiavi), 50)
        for v in catalogo.voci():
            self.assertTrue(v.formati, v.chiave)
            self.assertTrue(set(v.formati) <= set(catalogo.FORMATI), v.chiave)
            self.assertIn(v.layout, catalogo.LAYOUT_CHOICES, v.chiave)
            self.assertTrue(v.route or v.pagina, f"{v.chiave}: né route né pagina")

    def test_ogni_route_dichiarata_esiste(self):
        esistenti = _nomi_route()
        mancanti = [(v.chiave, r) for v in catalogo.voci() for r in v.route if r not in esistenti]
        self.assertEqual(mancanti, [])

    def test_ogni_pagina_si_apre_senza_argomenti(self):
        for v in catalogo.voci():
            if v.pagina:
                reverse(v.pagina)  # NoReverseMatch = voce sbagliata

    def test_voce_per_route(self):
        voce = catalogo.voce_per_route("anagrafica:formazione_sessione_mod040")
        self.assertEqual(voce.chiave, "formazione.mod040")
        self.assertTrue(voce.dati_personali)
        self.assertIsNone(catalogo.voce_per_route("non:esiste"))


class _Match:
    def __init__(self, view_name, kwargs=None):
        self.view_name = view_name
        self.kwargs = kwargs or {}


class DeveRegistrareTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def _req(self, view_name, autenticato=True, path="/x/"):
        req = self.rf.get(path, {"anno": "2026", "token": "segreto"})
        req.user = type("U", (), {"is_authenticated": autenticato})()
        req.resolver_match = _Match(view_name, {"pk": 7})
        return req

    @staticmethod
    def _pdf(**headers):
        resp = HttpResponse(b"%PDF-1.4 prova", content_type="application/pdf")
        for k, v in headers.items():
            resp[k] = v
        return resp

    def test_route_catalogata(self):
        ok, formato, voce = registro.deve_registrare(self._req("tickets:pdf"), self._pdf())
        self.assertTrue(ok)
        self.assertEqual(formato, "pdf")
        self.assertEqual(voce.chiave, "tickets.ticket")

    def test_route_non_catalogata_si_registra_senza_voce(self):
        ok, formato, voce = registro.deve_registrare(self._req("modulo:nuovo_export"), self._pdf())
        self.assertTrue(ok)
        self.assertIsNone(voce)

    def test_allegati_e_anteprime_esclusi(self):
        for nome in ("tickets:download_allegato", "dpi:documento_download", "schede_sicurezza:etichetta_anteprima"):
            self.assertFalse(registro.deve_registrare(self._req(nome), self._pdf())[0], nome)

    def test_streaming_solo_se_catalogato(self):
        import io

        resp = FileResponse(io.BytesIO(b"x"), content_type="application/pdf")
        self.assertFalse(registro.deve_registrare(self._req("modulo:file_caricato"), resp)[0])
        resp = FileResponse(io.BytesIO(b"x"), content_type="application/pdf")
        self.assertTrue(registro.deve_registrare(self._req("anagrafica:reportistica_archivio_download"), resp)[0])

    def test_html_errori_e_anonimi_esclusi(self):
        self.assertFalse(registro.deve_registrare(self._req("tickets:pdf"), HttpResponse("<p>ok</p>"))[0])
        errore = self._pdf()
        errore.status_code = 404
        self.assertFalse(registro.deve_registrare(self._req("tickets:pdf"), errore)[0])
        self.assertFalse(registro.deve_registrare(self._req("tickets:pdf", autenticato=False), self._pdf())[0])

    def test_formato_da_estensione(self):
        resp = HttpResponse(b"a;b", content_type="application/octet-stream")
        resp["Content-Disposition"] = 'attachment; filename="elenco.csv"'
        self.assertEqual(registro.formato_risposta(resp), "csv")

    def test_parametri_senza_segreti(self):
        parametri = registro._parametri(self._req("tickets:pdf"))
        self.assertEqual(parametri["anno"], "2026")
        self.assertNotIn("token", parametri)
        self.assertEqual(parametri["_route"], {"pk": "7"})


class _AdminClientMixin:
    def setUp(self):
        self.admin = User.objects.create_superuser(username="admin-rc", email="rc@test.local", password="pass12345")
        self.client.force_login(self.admin)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RegistroMiddlewareTests(_AdminClientMixin, TestCase):
    def test_scaricamento_registrato_con_impronta(self):
        ReportEmissione.objects.create(titolo="Prima", formato="pdf", report_chiave="tickets.ticket", modulo="tickets")
        resp = self.client.get(reverse("admin_portale:centro_report_registro_csv"), {"giorni": "30"})
        self.assertEqual(resp.status_code, 200)
        e = ReportEmissione.objects.filter(report_chiave="admin_portale.registro_emissioni").get()
        self.assertEqual(e.formato, "csv")
        self.assertEqual(e.nome_file, "registro-emissioni-report.csv")
        self.assertEqual(e.sha256, hashlib.sha256(resp.content).hexdigest())
        self.assertEqual(e.dimensione_byte, len(resp.content))
        self.assertTrue(e.dati_personali)
        self.assertEqual(e.parametri.get("giorni"), "30")
        self.assertIn("Prima", resp.content.decode("utf-8"))

    def test_errore_di_scrittura_non_blocca_il_download(self):
        with patch("core.report_centro.registro.registra", side_effect=RuntimeError("db giù")):
            resp = self.client.get(reverse("admin_portale:centro_report_registro_csv"))
        self.assertEqual(resp.status_code, 200)

    def test_pulizia_rispetta_la_soglia(self):
        vecchia = ReportEmissione.objects.create(titolo="vecchia", formato="pdf")
        ReportEmissione.objects.filter(pk=vecchia.pk).update(created_at=timezone.now() - timedelta(days=40))
        ReportEmissione.objects.create(titolo="nuova", formato="pdf")
        self.assertEqual(registro.pulisci_scadute(0), 0)
        self.assertEqual(registro.pulisci_scadute(30), 1)
        self.assertEqual(list(ReportEmissione.objects.values_list("titolo", flat=True)), ["nuova"])

    def test_schedule_notturno_registrato(self):
        from automazioni.schedules import SCHEDULES
        from core.tasks import run_report_emissioni_pulizia

        self.assertIn("core.tasks.run_report_emissioni_pulizia", {s["func"] for s in SCHEDULES})
        registro.imposta_conservazione(0)
        self.assertEqual(run_report_emissioni_pulizia(), {"ok": True, "giorni": 0, "eliminate": 0})


class LayoutTests(TestCase):
    def setUp(self):
        self.globale = ReportProfiloLayout.objects.create(nome="Ufficiale", colore_primario="#112233", piede_pagina="Uso interno")
        self.bozza = ReportProfiloLayout.objects.create(nome="Bozza", filigrana="BOZZA", mostra_numero_pagina=False)

    def test_modulo_e_voce(self):
        from core.pdf import PdfTheme

        ReportAssegnazioneLayout.objects.create(ambito="modulo", chiave="tickets", profilo=self.globale)
        tema = PdfTheme.from_branding(voce="tickets.ticket")
        self.assertEqual(tema.primary, "#112233")
        self.assertEqual(tema.footer_text, "Uso interno")
        self.assertEqual(tema.profile_name, "Ufficiale")
        self.assertEqual(tema.watermark, "")

        ReportAssegnazioneLayout.objects.create(ambito="voce", chiave="tickets.ticket", profilo=self.bozza)
        tema = PdfTheme.from_branding(voce="tickets.ticket")
        self.assertEqual(tema.watermark, "BOZZA")
        self.assertFalse(tema.show_page_number)

    def test_profilo_disattivato_ignorato(self):
        from core.pdf import PdfTheme

        self.globale.is_active = False
        self.globale.save()
        ReportAssegnazioneLayout.objects.create(ambito="modulo", chiave="tickets", profilo=self.globale)
        self.assertEqual(PdfTheme.from_branding(voce="tickets.ticket").profile_name, "")

    def test_senza_richiesta_ne_voce_template_globale(self):
        from core.pdf import PdfTheme

        self.assertIsNone(layout.profilo_corrente())
        self.assertEqual(PdfTheme.from_branding().profile_name, "")

    def test_filigrana_disegnata(self):
        from io import BytesIO

        from reportlab.pdfgen import canvas

        from core.pdf import PdfTheme, draw_canvas_header

        ReportAssegnazioneLayout.objects.create(ambito="voce", chiave="tickets.ticket", profilo=self.bozza)
        tema = PdfTheme.from_branding(voce="tickets.ticket")
        buf = BytesIO()
        c = canvas.Canvas(buf)
        draw_canvas_header(c, theme=tema, page_width=595, page_height=842, left_margin=50, right_margin=50, title="T")
        c.save()
        self.assertTrue(buf.getvalue().startswith(b"%PDF"))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PaginaCentroReportTests(_AdminClientMixin, TestCase):
    url = "admin_portale:centro_report"

    def test_schede(self):
        ReportEmissione.objects.create(titolo="x.pdf", formato="pdf", route_name="modulo:nuovo_export")
        for scheda, atteso in (
            ("catalogo", "Route da catalogare"),
            ("registro", "Conservazione del registro"),
            ("layout", "Profili di layout"),
            ("guida", 'id="guida-registro"'),
        ):
            resp = self.client.get(reverse(self.url), {"tab": scheda})
            self.assertEqual(resp.status_code, 200, scheda)
            self.assertContains(resp, atteso)
        resp = self.client.get(reverse(self.url))
        self.assertContains(resp, "MOD.040 Verbale di formazione")
        self.assertContains(resp, "modulo:nuovo_export")

    def test_profilo_assegnazione_anteprima(self):
        azione = reverse("admin_portale:centro_report_azione")
        resp = self.client.post(azione, {
            "azione": "profilo_salva", "nome": "Copia controllata", "colore_primario": "#ABCDEF",
            "filigrana": "COPIA", "mostra_data_generazione": "1", "mostra_numero_pagina": "1", "is_active": "1",
        })
        self.assertEqual(resp.status_code, 302)
        profilo = ReportProfiloLayout.objects.get(nome="Copia controllata")
        self.assertEqual(profilo.colore_primario, "#abcdef")

        self.client.post(azione, {"azione": "assegnazioni_salva", "modulo__tickets": str(profilo.pk),
                                  "voce__tickets.ticket": "", "voce__inventato.x": str(profilo.pk)})
        self.assertEqual(
            list(ReportAssegnazioneLayout.objects.values_list("ambito", "chiave")), [("modulo", "tickets")]
        )
        self.client.post(azione, {"azione": "assegnazioni_salva", "modulo__tickets": ""})
        self.assertFalse(ReportAssegnazioneLayout.objects.exists())

        resp = self.client.get(reverse("admin_portale:centro_report_anteprima", args=[profilo.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertFalse(ReportEmissione.objects.exists())  # le anteprime non finiscono nel registro

    def test_profilo_non_valido(self):
        resp = self.client.post(reverse("admin_portale:centro_report_azione"), {
            "azione": "profilo_salva", "nome": "X", "colore_primario": "rosso",
        }, follow=True)
        self.assertContains(resp, "#RRGGBB")
        self.assertFalse(ReportProfiloLayout.objects.exists())

    def test_conservazione(self):
        self.client.post(reverse("admin_portale:centro_report_azione"), {"azione": "conservazione", "giorni": "99999"})
        self.assertEqual(SiteConfig.get(registro.RETENTION_KEY), str(registro.MAX_GIORNI))

    def test_non_admin_respinto(self):
        utente = User.objects.create_user(username="semplice-rc", password="pass12345")
        self.client.force_login(utente)
        resp = self.client.get(reverse(self.url))
        self.assertNotEqual(resp.status_code, 200)
