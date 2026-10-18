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

    def test_registro_collega_archivio_hr(self):
        from anagrafica.models_reportistica import ReportGenerato

        impronta = "e" * 64
        ReportGenerato.objects.create(titolo="Organico", formato="pdf", nome_file="org.pdf", contenuto=b"x", sha256=impronta)
        ReportEmissione.objects.create(titolo="Organico", formato="pdf", sha256=impronta, report_chiave="anagrafica.reportistica")
        ReportEmissione.objects.create(titolo="Altro", formato="pdf", sha256="f" * 64)
        resp = self.client.get(reverse(self.url), {"tab": "registro"})
        self.assertContains(resp, "Copia in archivio HR", count=1)

    def test_conservazione(self):
        self.client.post(reverse("admin_portale:centro_report_azione"), {"azione": "conservazione", "giorni": "99999"})
        self.assertEqual(SiteConfig.get(registro.RETENTION_KEY), str(registro.MAX_GIORNI))

    def test_non_admin_respinto(self):
        utente = User.objects.create_user(username="semplice-rc", password="pass12345")
        self.client.force_login(utente)
        resp = self.client.get(reverse(self.url))
        self.assertNotEqual(resp.status_code, 200)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MieiReportTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.utente = User.objects.create_user(username="dipendente-rc", password="pass12345")
        UserOnboarding.objects.create(user=self.utente, completed=True)
        self.client.force_login(self.utente)

    def _get(self, consentiti=("/tickets/",), legacy_id=77, **params):
        legacy = type("L", (), {"id": legacy_id})()

        def finto_acl(path, **kwargs):
            return path in consentiti

        with patch("core.middleware.acl_allows_path", side_effect=finto_acl), patch(
            "core.legacy_utils.get_legacy_user", return_value=legacy
        ):
            return self.client.get(reverse("miei_report"), params)

    def test_mostra_solo_i_report_delle_pagine_accessibili(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Scheda ticket")
        self.assertNotContains(resp, "MOD.040 Verbale di formazione")
        self.assertEqual(resp.context["totale_voci"], 1)

    def test_nessun_permesso(self):
        resp = self._get(consentiti=())
        self.assertContains(resp, "non ci sono report da generare")

    def test_solo_i_propri_scaricamenti(self):
        ReportEmissione.objects.create(legacy_user_id=77, titolo="Mio ticket", formato="pdf", report_chiave="tickets.ticket")
        ReportEmissione.objects.create(legacy_user_id=88, titolo="Di un altro", formato="pdf")
        resp = self._get()
        self.assertContains(resp, "Mio ticket")
        self.assertNotContains(resp, "Di un altro")

    def test_guida_e_rotta_condivisa(self):
        from core.middleware import is_acl_shared_path

        self.assertTrue(is_acl_shared_path(reverse("miei_report")))
        resp = self._get(guida="1")
        self.assertContains(resp, 'id="guida-dati"')

    def test_link_nel_menu_utente(self):
        resp = self._get()
        self.assertContains(resp, f'href="{reverse("miei_report")}"')



class CalendarioPianificazioneTests(SimpleTestCase):
    def _p(self, **kw):
        from core.models import ReportPianificazione

        return ReportPianificazione(**{"frequenza": "mensile", "giorno_mese": 1, "giorno_settimana": 0, "ora": 7, **kw})

    def test_settimanale(self):
        from datetime import datetime

        from core.report_centro.pianificazione import calcola_prossima

        tz = timezone.get_current_timezone()
        mercoledi = datetime(2026, 10, 14, 9, 0, tzinfo=tz)
        p = self._p(frequenza="settimanale", giorno_settimana=0, ora=7)
        self.assertEqual(timezone.localtime(calcola_prossima(p, mercoledi)).date().isoformat(), "2026-10-19")
        p = self._p(frequenza="settimanale", giorno_settimana=2, ora=10)
        self.assertEqual(timezone.localtime(calcola_prossima(p, mercoledi)).strftime("%Y-%m-%d %H"), "2026-10-14 10")
        p = self._p(frequenza="settimanale", giorno_settimana=2, ora=8)
        self.assertEqual(timezone.localtime(calcola_prossima(p, mercoledi)).date().isoformat(), "2026-10-21")

    def test_mensile_e_fine_anno(self):
        from datetime import datetime

        from core.report_centro.pianificazione import calcola_prossima

        tz = timezone.get_current_timezone()
        p = self._p(giorno_mese=5, ora=6)
        self.assertEqual(timezone.localtime(calcola_prossima(p, datetime(2026, 10, 3, tzinfo=tz))).date().isoformat(), "2026-10-05")
        self.assertEqual(timezone.localtime(calcola_prossima(p, datetime(2026, 12, 20, tzinfo=tz))).date().isoformat(), "2027-01-05")

    def test_varianti_del_catalogo_valide(self):
        varianti = catalogo.varianti_pianificabili()
        self.assertGreaterEqual(len(varianti), 8)
        for voce, var in varianti:
            reverse(var.route)
            self.assertIn(var.route, voce.route, voce.chiave)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_FROM_EMAIL="hub@example.com")
class PianificazioneTests(TestCase):
    def setUp(self):
        from core.models import ReportPianificazione

        self.proprietario = User.objects.create_superuser(username="proprietario", email="prop@example.com", password="x")
        self.ammesso = User.objects.create_user(username="ammesso", email="ammesso@example.com", first_name="Anna", last_name="Neri")
        self.escluso = User.objects.create_user(username="escluso", email="escluso@example.com")
        self.voce = catalogo.ReportVoce(
            chiave="admin_portale.registro_emissioni", nome="Registro emissioni report", descrizione="",
            formati=("csv",), route=("admin_portale:centro_report_registro_csv",), dati_personali=True,
            modulo="admin_portale", modulo_etichetta="Amministrazione",
            varianti=(catalogo.Variante("tutto", "Tutto il registro", "admin_portale:centro_report_registro_csv"),),
        )
        self.p = ReportPianificazione.objects.create(
            nome="Registro settimanale", voce_chiave=self.voce.chiave, variante="tutto",
            frequenza="settimanale", proprietario=self.proprietario,
        )
        self.p.destinatari.set([self.ammesso, self.escluso])

    def _patch(self):
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(patch("core.report_centro.pianificazione.catalogo.voce_per_chiave", return_value=self.voce))
        stack.enter_context(patch(
            "core.middleware.acl_allows_path",
            side_effect=lambda path, django_user=None, **kw: getattr(django_user, "username", "") != "escluso",
        ))
        return stack

    def test_genera_invia_e_registra(self):
        from django.core import mail

        from core.report_centro.pianificazione import esegui

        with self._patch():
            esito = esegui(self.p, manuale=True)
        self.assertEqual(esito.esito, "parziale", esito.messaggio)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ammesso@example.com"])
        nome, contenuto, tipo = mail.outbox[0].attachments[0]
        self.assertEqual(nome, "registro-emissioni-report.csv")
        self.assertEqual(tipo, "text/csv")
        e = ReportEmissione.objects.get(route_name=f"pianificazione:{self.p.pk}")
        self.assertEqual(e.parametri["destinatari"], 1)
        self.assertEqual(e.parametri["esclusi"], 1)
        self.p.refresh_from_db()
        self.assertEqual(self.p.ultimo_esito, "parziale")
        self.assertIsNotNone(self.p.prossima_esecuzione)

    def test_proprietario_senza_permessi_errore(self):
        from django.core import mail

        from core.report_centro.pianificazione import esegui

        self.p.proprietario = self.ammesso
        self.p.save()
        with self._patch():
            esito = esegui(self.p)
        self.assertEqual(esito.esito, "errore")
        self.assertIn("403", esito.messaggio)
        self.assertEqual(len(mail.outbox), 0)

    def test_esegui_scadute_solo_attive_e_dovute(self):
        from core.models import ReportPianificazione
        from core.report_centro.pianificazione import esegui_scadute

        ReportPianificazione.objects.filter(pk=self.p.pk).update(prossima_esecuzione=timezone.now() - timedelta(minutes=5))
        futura = ReportPianificazione.objects.create(
            nome="Futura", voce_chiave=self.voce.chiave, variante="tutto", proprietario=self.proprietario,
            prossima_esecuzione=timezone.now() + timedelta(days=1))
        sospesa = ReportPianificazione.objects.create(
            nome="Sospesa", voce_chiave=self.voce.chiave, variante="tutto", proprietario=self.proprietario,
            attiva=False, prossima_esecuzione=timezone.now() - timedelta(days=1))
        with self._patch():
            conteggi = esegui_scadute()
        self.assertEqual(conteggi["eseguite"], 1)
        futura.refresh_from_db()
        sospesa.refresh_from_db()
        self.assertIsNone(futura.ultima_esecuzione)
        self.assertIsNone(sospesa.ultima_esecuzione)

    def test_schedule_orario(self):
        from automazioni.schedules import SCHEDULES

        self.assertIn("core.tasks.run_report_pianificati", {s["func"] for s in SCHEDULES})

    def test_pagina_admin_e_salvataggio(self):
        from core.models import ReportPianificazione

        self.client.force_login(self.proprietario)
        resp = self.client.get(reverse("admin_portale:centro_report"), {"tab": "pianificazioni"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Registro settimanale")
        self.assertContains(resp, "NERI ANNA")
        resp = self.client.post(reverse("admin_portale:centro_report_azione"), {
            "azione": "pianificazione_salva", "nome": "Visite HR", "variante": "visite.scadenze|prossimo",
            "frequenza": "mensile", "giorno_mese": "3", "ora": "8", "destinatari": [str(self.ammesso.pk)], "attiva": "1",
        })
        self.assertEqual(resp.status_code, 302)
        nuova = ReportPianificazione.objects.get(nome="Visite HR")
        self.assertEqual(list(nuova.destinatari.all()), [self.ammesso])
        self.assertEqual(timezone.localtime(nuova.prossima_esecuzione).day, 3)
        self.client.post(reverse("admin_portale:centro_report_azione"),
                         {"azione": "pianificazione_attiva", "pianificazione_id": nuova.pk})
        nuova.refresh_from_db()
        self.assertFalse(nuova.attiva)

    def test_variante_non_valida_rifiutata(self):
        from core.models import ReportPianificazione

        self.client.force_login(self.proprietario)
        self.client.post(reverse("admin_portale:centro_report_azione"), {
            "azione": "pianificazione_salva", "nome": "X", "variante": "tickets.ticket|tutto",
            "frequenza": "mensile", "destinatari": [str(self.ammesso.pk)],
        })
        self.assertFalse(ReportPianificazione.objects.filter(nome="X").exists())

    def test_ricevuti_in_i_miei_report(self):
        from core.models import UserOnboarding

        UserOnboarding.objects.create(user=self.ammesso, completed=True)
        self.client.force_login(self.ammesso)
        with patch("core.middleware.acl_allows_path", return_value=False):
            resp = self.client.get(reverse("miei_report"))
        self.assertContains(resp, "Ricevi per mail")
        self.assertContains(resp, "Registro settimanale")
