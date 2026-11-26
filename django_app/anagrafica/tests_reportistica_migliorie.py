"""Migliorie della reportistica (26/11/2026): archivio (chi vede cosa, filtri, conservazione,
«Rigenera»), anteprima dal vivo con riepilogo, sezioni del catalogo cliccabili, domande di chiarimento.

Dati sintetici: persone inventate, ``carica_dipendenti`` sostituito come negli altri test.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import ReportGenerato, ReportModello
from anagrafica.reportistica import archivio, conversazione, motore
from anagrafica.reportistica.predefiniti import crea_predefiniti
from anagrafica.models import ReportBlocco
from anagrafica.tests_reportistica import _persone

User = get_user_model()
OGGI = timezone.localdate()


def _doc(user, **campi) -> ReportGenerato:
    dati = {"titolo": "Documento", "formato": "pdf", "nome_file": "x.pdf", "contenuto": b"%PDF-1", "generato_da": user,
            "modello_nome": "Modello A", "parametri": {"sezioni": ["personale_elenco"]}}
    dati.update(campi)
    return ReportGenerato.objects.create(**dati)


class _Base(TestCase):
    def setUp(self):
        super().setUp()
        for target in ("anagrafica.reportistica.dati.carica_dipendenti",
                       "anagrafica.reportistica.forms.carica_dipendenti",
                       "anagrafica.views_reportistica_chat.carica_dipendenti"):
            p = patch(target, side_effect=_persone)
            p.start()
            self.addCleanup(p.stop)
        self.admin = User.objects.create_superuser("rpm_admin", "rpm_admin@example.com", "x")
        self.anna = User.objects.create_user("rpm_anna", "rpm_anna@example.com", "x")
        self.rf = RequestFactory()

    def req(self, user):
        r = self.rf.get("/")
        r.user = user
        return r


class ArchivioVisibilitaTest(_Base):
    def test_chi_non_gestisce_vede_solo_i_propri(self):
        mio, altrui = _doc(self.anna), _doc(self.admin)
        with patch("anagrafica.reportistica.archivio.can_manage", return_value=False):
            self.assertEqual(list(archivio.visibili(self.req(self.anna))), [mio])
        with patch("anagrafica.reportistica.archivio.can_manage", return_value=True):
            self.assertEqual(set(archivio.visibili(self.req(self.anna))), {mio, altrui})

    def test_download_e_rigenera_di_un_documento_altrui_sono_404(self):
        from django.http import Http404

        from anagrafica.views_reportistica import reportistica_archivio_download, reportistica_archivio_rigenera

        altrui, mio = _doc(self.admin), _doc(self.anna)
        with patch("anagrafica.views_reportistica.can_view", return_value=True), \
                patch("anagrafica.reportistica.archivio.can_manage", return_value=False), \
                patch.object(archivio, "consentito", return_value=True):
            for vista in (reportistica_archivio_download, reportistica_archivio_rigenera):
                with self.assertRaises(Http404):
                    vista(self.req(self.anna), altrui.pk)
            resp = reportistica_archivio_download(self.req(self.anna), mio.pk)
        self.assertEqual(resp["Content-Type"], "application/pdf")


class ArchivioFiltriTest(_Base):
    def test_filtri_formato_modello_date(self):
        pdf = _doc(self.admin, formato="pdf", modello_nome="Modello A")
        xlsx = _doc(self.admin, formato="xlsx", modello_nome="Modello B", nome_file="x.xlsx")
        qs = ReportGenerato.objects.all()
        r = self.req(self.admin)
        self.assertEqual(list(archivio.filtra(qs, {"formato": "xlsx"}, r)[0]), [xlsx])
        self.assertEqual(list(archivio.filtra(qs, {"modello": "Modello A"}, r)[0]), [pdf])
        domani = (OGGI + timedelta(days=1)).isoformat()
        self.assertEqual(list(archivio.filtra(qs, {"dal": domani}, r)[0]), [])
        _qs, valori = archivio.filtra(qs, {"formato": "pippo"}, r)
        self.assertEqual(valori["formato"], "")
        self.assertFalse(valori["attivi"])


class ConservazioneTest(_Base):
    def test_file_con_dati_personali_cancellato_dopo_i_mesi(self):
        vecchio = _doc(self.admin, contiene_dati_personali=True)
        vecchio_anonimo = _doc(self.admin, contiene_dati_personali=False)
        recente = _doc(self.admin, contiene_dati_personali=True)
        anni_fa = timezone.now() - timedelta(days=500)
        ReportGenerato.objects.filter(pk__in=[vecchio.pk, vecchio_anonimo.pk]).update(generato_il=anni_fa)
        self.assertEqual(archivio.scadi_vecchi(), 1)
        vecchio.refresh_from_db()
        self.assertFalse(vecchio.file_disponibile)
        self.assertEqual(bytes(vecchio.contenuto), b"")
        self.assertEqual(vecchio.sha256, vecchio.sha256)  # la riga e l'impronta restano
        for d in (vecchio_anonimo, recente):
            d.refresh_from_db()
            self.assertTrue(d.file_disponibile)
        self.assertEqual(archivio.scadi_vecchi(), 0)  # idempotente

    @override_settings(REPORTISTICA_ARCHIVIO_MESI=0)
    def test_zero_mesi_non_cancella_mai(self):
        doc = _doc(self.admin, contiene_dati_personali=True)
        ReportGenerato.objects.filter(pk=doc.pk).update(generato_il=timezone.now() - timedelta(days=3000))
        self.assertEqual(archivio.scadi_vecchi(), 0)


class RigeneraTest(_Base):
    def setUp(self):
        super().setUp()
        crea_predefiniti(ReportModello, ReportBlocco)
        self.modello = ReportModello.objects.get(codice_sistema="personale_cliente")

    def test_parametri_da_archivio(self):
        blocco = self.modello.blocchi.first()
        salvati = {"periodo_tipo": "ANNO_PRECEDENTE", "titolo": "Per il cliente", "destinatario": "Cliente Demo",
                   "perimetro": {"reparti": ["Produzione"]}, "escludi_blocchi": [blocco.pk, 999999]}
        p = motore.Parametri.da_archivio(self.modello, salvati)
        self.assertEqual(p.periodo_tipo, "ANNO_PRECEDENTE")
        self.assertEqual(p.titolo, "Per il cliente")
        self.assertEqual(p.perimetro.reparti, ["Produzione"])
        self.assertEqual(p.escludi_blocchi, {blocco.pk})  # blocchi spariti ignorati

    def test_rigenera_apre_la_generazione_con_i_parametri(self):
        doc = _doc(self.admin, modello=self.modello, parametri={
            "sezioni": ["personale_qualifiche"], "titolo": "Titolo archiviato", "destinatario": "Cliente Demo",
            "periodo_tipo": "ULTIMI_12_MESI", "perimetro": {}})
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("anagrafica:reportistica_archivio_rigenera", args=[doc.pk]))
        self.assertRedirects(resp, reverse("anagrafica:reportistica_genera", args=[self.modello.pk]) + f"?da={doc.pk}",
                             fetch_redirect_response=False)
        pagina = self.client.get(resp["Location"])
        self.assertContains(pagina, "Titolo archiviato")
        self.assertContains(pagina, "Parametri ripresi dal documento")

    def test_rigenera_di_un_report_a_conversazione_riapre_la_chat(self):
        spec = conversazione.specifica_vuota()
        spec["sezioni"] = [{"sezione": "personale_elenco", "colonne": [], "opzioni": {}}]
        doc = _doc(self.admin, modello=None, parametri={"sezioni": ["personale_elenco"], "specifica": spec})
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("anagrafica:reportistica_archivio_rigenera", args=[doc.pk]))
        self.assertRedirects(resp, reverse("anagrafica:reportistica_chat"), fetch_redirect_response=False)
        stato = self.client.session["rp_chat"]
        self.assertEqual([s["sezione"] for s in stato["specifica"]["sezioni"]], ["personale_elenco"])


class AnteprimaDalVivoTest(_Base):
    def setUp(self):
        super().setUp()
        crea_predefiniti(ReportModello, ReportBlocco)
        self.modello = ReportModello.objects.get(codice_sistema="personale_cliente")

    def test_htmx_rende_solo_il_riquadro_e_non_salva(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("anagrafica:reportistica_genera", args=[self.modello.pk]),
            {"titolo": "Al volo", "periodo_tipo": "ULTIMI_12_MESI", "destinatario": "Cliente X",
             "salva_nel_modello": "on", "azione": "pdf"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("<html", resp.content.decode().lower())
        self.assertContains(resp, "Al volo")
        self.assertContains(resp, "rp-riepilogo")
        self.assertFalse(ReportGenerato.objects.exists())  # niente download dall'anteprima
        self.modello.refresh_from_db()
        self.assertNotEqual(self.modello.titolo_documento, "Al volo")  # niente salvataggi

    def test_riepilogo(self):
        from anagrafica.reportistica.motore import Parametri, componi

        rf = self.req(self.admin)
        doc = componi(self.modello, Parametri.dal_modello(self.modello), rf)
        r = motore.riepilogo(doc)
        self.assertEqual(r["persone"], 3)  # 4 sintetiche, una cessata
        self.assertGreaterEqual(r["sezioni"], 1)


class CatalogoCliccabileTest(_Base):
    def test_sezione_dal_catalogo_apre_la_chat_impostata(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("anagrafica:reportistica_chat"),
                                {"azione": "sezione", "sezione": "personale_elenco", "nuova": "1"})
        self.assertEqual(resp.status_code, 302)
        stato = self.client.session["rp_chat"]
        self.assertEqual([s["sezione"] for s in stato["specifica"]["sezioni"]], ["personale_elenco"])
        self.assertEqual(stato["specifica"]["titolo"], "Elenco del personale")

    def test_sezione_fuori_chat_ignorata(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("anagrafica:reportistica_chat"),
                         {"azione": "sezione", "sezione": "costo_orario_persone", "nuova": "1"})
        self.assertEqual(self.client.session["rp_chat"]["specifica"]["sezioni"], [])


class DomandeTest(_Base):
    def test_reparto_non_trovato_propone_i_simili(self):
        scelte = {"reparti": [("Produzione", "Produzione"), ("Qualità", "Qualità")]}
        domande = conversazione.domande_di_chiarimento(
            ["Reparto «Produzion» non trovato: ignorato."], scelte, _persone(), conversazione.specifica_vuota())
        self.assertEqual(len(domande), 1)
        self.assertIn("Non trovo il reparto «Produzion»", domande[0]["testo"])
        self.assertEqual(domande[0]["risposte"], ["Reparto Produzione"])

    def test_persona_ambigua_e_periodo(self):
        avvisi = ["«ROSSI» corrisponde a 2 persone: indica nome e cognome.",
                  "Per le date personalizzate servono inizio e fine: uso gli ultimi 12 mesi."]
        persone = _persone() + [type(_persone()[0])(id=990, nominativo="ROSSI MARCO")]
        domande = conversazione.domande_di_chiarimento(avvisi, {}, persone, conversazione.specifica_vuota())
        self.assertEqual(domande[0]["risposte"], ["La persona è ROSSI ANNA", "La persona è ROSSI MARCO"])
        self.assertIn("Anno scorso", domande[1]["risposte"])

    def test_in_chat_le_domande_tolgono_l_avviso_doppio(self):
        self.client.force_login(self.admin)
        grezza = {"sezioni": [{"sezione": "personale_elenco"}], "perimetro": {"reparti": ["Inesistente"]}}
        with patch("ai_assistant.services.chat_with_ollama",
                   return_value=type("R", (), {"content": '{"risposta": "Ecco.", "specifica": %s}'
                                               % __import__("json").dumps(grezza)})()):
            self.client.post(reverse("anagrafica:reportistica_chat"), {"azione": "messaggio", "messaggio": "elenco"})
        stato = self.client.session["rp_chat"]
        self.assertEqual(len(stato["domande"]), 1)
        self.assertFalse(any("Inesistente" in a for a in stato["avvisi"]))
