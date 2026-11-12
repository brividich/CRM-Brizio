"""Menu del modulo, pagina «Da fare», scheda del certificato e collegamento a Formazione. Dati sintetici."""
from __future__ import annotations

import re
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from anagrafica.models import DipendenteQualifica, TipoQualifica
from core.models import SiteConfig
from report_conformita.registry import ReportParams, get_report

from .acl_bootstrap import _ROUTE_BINDINGS, PERM_AUDIT_EDIT, PERM_AUDIT_VIEW
from .models import AuditEsterno, Auditor, Certificazione, CertificazioneDocumento
from .services import panoramica
from .services.qualifiche import CHIAVE_TIPO_AUDITOR, copertura_qualifiche
from .storage import PrivateSistemaGestioneStorage
from .templatetags.sg_guida import _sezione, sg_menu


def _cert(**kw):
    dati = {"norma": "EN9100", "ente": "Ente Prova", "scade_il": timezone.localdate() + timedelta(days=400)}
    dati.update(kw)
    return Certificazione.objects.create(**dati)


class BaseTest(TestCase):
    def setUp(self):
        self.su = get_user_model().objects.create_superuser("sgi_su", password="x")
        self.client.force_login(self.su)


class MenuTests(BaseTest):
    def test_le_sezioni_seguono_il_nome_della_pagina(self):
        for vista, attesa in (("sistema_gestione:index", "panoramica"), ("sistema_gestione:esterni_audit", "certificazioni"),
                              ("sistema_gestione:auditor_modifica", "auditor"), ("sistema_gestione:processo_dettaglio", "processi"),
                              ("sistema_gestione:checklist_norme", "checklist"), ("sistema_gestione:soa_voce", "soa"),
                              ("sistema_gestione:threat_intelligence", "soa"), ("sistema_gestione:audit_cruscotto", "audit")):
            self.assertEqual(_sezione(vista), attesa, vista)

    def test_le_pagine_mostrano_il_menu_e_non_commenti_a_video(self):
        for rotta in ("index", "audit_index", "esterni_elenco", "auditor_elenco", "processi_catalogo", "checklist_norme"):
            r = self.client.get(reverse(f"sistema_gestione:{rotta}"))
            self.assertEqual(r.status_code, 200, rotta)
            html = r.content.decode()
            self.assertIn('class="sg-menu"', html, rotta)
            self.assertNotIn("{#", html, rotta)

    def test_i_pulsanti_sono_spariti_dalla_testata_degli_audit(self):
        html = self.client.get(reverse("sistema_gestione:audit_index")).content.decode()
        testata = html[html.index('class="page-header"'):html.index("Dal processo al rapporto")]
        self.assertNotIn("Cicli triennali", testata)
        self.assertIn("Nuovo audit", testata)
        self.assertIn("Cicli triennali", html)  # adesso sta nel menu

    def test_chi_non_ha_il_permesso_non_vede_la_voce(self):
        def perm(_request, codice):
            return codice in {"sistema_gestione.modulo.view", PERM_AUDIT_VIEW}

        request = RequestFactory().get(reverse("sistema_gestione:audit_index"))
        request.user = self.su
        request.resolver_match = resolve(reverse("sistema_gestione:audit_index"))
        with patch("sistema_gestione.views._has_perm", side_effect=perm), \
                patch("core.middleware.acl_allows_path", return_value=False):
            menu = sg_menu({"request": request})
        sezioni = [v["etichetta"] for v in menu["sezioni"]]
        sotto = [v["etichetta"] for v in menu["sotto"]]
        self.assertIn("Audit interni", sezioni)
        self.assertNotIn("SoA 27001", sezioni)
        self.assertIn("Calendario", sotto)
        self.assertNotIn("Impostazioni", sotto)
        self.assertEqual(menu["collegati"], [])


class DaFareTests(BaseTest):
    def test_elenco_vuoto_su_db_vuoto_a_parte_il_programma(self):
        voci = panoramica.da_fare()
        self.assertEqual([v["testo"].split()[0] for v in voci], ["Programma"])

    def test_scaduto_prima_di_tutto_e_ogni_voce_ha_il_link(self):
        oggi = timezone.localdate()
        scaduto = _cert(scade_il=oggi - timedelta(days=1))
        CertificazioneDocumento.objects.create(certificazione=scaduto, nome="c.pdf", sha256="0" * 64, file="x.pdf")
        _cert(norma="ISO45001", prossima_sorveglianza=oggi - timedelta(days=2))
        voci = panoramica.da_fare(oggi)
        self.assertEqual(voci[0]["testo"], "Certificato EN 9100 scaduto")
        self.assertEqual(voci[0]["tono"], "danger")
        self.assertTrue(all(v["url"] for v in voci))
        self.assertTrue(any("data superata" in v["testo"] for v in voci))
        self.assertTrue(any("manca la copia" in v["testo"] and "45001" in v["testo"] for v in voci))
        self.assertFalse(any("manca la copia" in v["testo"] and "9100" in v["testo"] for v in voci))

    def test_certificato_ritirato_ignorato(self):
        oggi = timezone.localdate()
        _cert(attiva=False, scade_il=oggi - timedelta(days=5))
        self.assertFalse(any("scaduto" in v["testo"] for v in panoramica.da_fare(oggi)))

    def test_la_pagina_iniziale_mostra_le_voci(self):
        _cert(scade_il=timezone.localdate() - timedelta(days=1))
        html = self.client.get(reverse("sistema_gestione:index")).content.decode()
        self.assertIn("In ritardo · 1", html)
        self.assertIn("Certificato EN 9100 scaduto", html)

    def test_colonne_ogni_voce_in_una_sola_per_data(self):
        oggi = timezone.localdate()
        voce = panoramica._voce
        voci = [voce(panoramica.MEDIA, "ieri", "/a", "Apri", oggi - timedelta(days=1)),
                voce(panoramica.ALTA, "alta senza data", "/a", "Apri"),
                voce(panoramica.BASSA, "oggi", "/a", "Apri", oggi),
                voce(panoramica.BASSA, "limite", "/a", "Apri", oggi + timedelta(days=30)),
                voce(panoramica.MEDIA, "oltre", "/a", "Apri", oggi + timedelta(days=31)),
                voce(panoramica.MEDIA, "senza", "/a", "Apri")]
        testi = {c["chiave"]: [v["testo"] for v in c["voci"]] for c in panoramica.colonne(voci, oggi)}
        self.assertEqual(testi, {"ritardo": ["ieri", "alta senza data"], "vicino": ["oggi", "limite"],
                                 "avanti": ["oltre"], "senza": ["senza"]})

    def test_piu_certificati_senza_copia_in_una_voce_sola(self):
        _cert()
        _cert(norma="ISO45001")
        voci = [v for v in panoramica.da_fare() if "copia in PDF" in v["testo"]]
        self.assertEqual([v["testo"] for v in voci], ["Manca la copia in PDF di 2 certificati"])


class SchedaCertificatoTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.radice = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.radice, ignore_errors=True)
        campo = CertificazioneDocumento._meta.get_field("file")
        vecchio = campo.storage
        nuovo = PrivateSistemaGestioneStorage()
        nuovo._location = self.radice
        nuovo.__dict__.pop("base_location", None)
        nuovo.__dict__.pop("location", None)
        campo.storage = nuovo
        self.addCleanup(setattr, campo, "storage", vecchio)

    def test_rotte_nuove_legate_al_permesso_giusto(self):
        self.assertEqual(_ROUTE_BINDINGS["sistema_gestione:esterni_certificazione_scheda"], PERM_AUDIT_VIEW)
        self.assertEqual(_ROUTE_BINDINGS["sistema_gestione:esterni_certificazione_documento"], PERM_AUDIT_VIEW)
        self.assertEqual(_ROUTE_BINDINGS["sistema_gestione:esterni_certificazione_documento_carica"], PERM_AUDIT_EDIT)

    def test_carica_e_scarica_con_storico(self):
        c = _cert(emesso_il=timezone.localdate() - timedelta(days=10))
        url = reverse("sistema_gestione:esterni_certificazione_documento_carica", args=[c.pk])
        for nome in ("primo.pdf", "secondo.pdf"):
            r = self.client.post(url, {"file": SimpleUploadedFile(nome, b"%PDF-1.4 prova", "application/pdf")})
            self.assertEqual(r.status_code, 302)
        docs = list(c.documenti.all())
        self.assertEqual([d.nome for d in docs], ["secondo.pdf", "primo.pdf"])
        self.assertEqual(len(docs[0].sha256), 64)
        self.assertEqual(docs[0].scade_il, c.scade_il)
        r = self.client.get(reverse("sistema_gestione:esterni_certificazione_documento", args=[c.pk, docs[0].pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 prova")
        html = self.client.get(reverse("sistema_gestione:esterni_certificazione_scheda", args=[c.pk])).content.decode()
        self.assertIn("secondo.pdf", html)
        self.assertIn("primo.pdf", html)

    def test_rifiuta_un_file_che_non_e_pdf(self):
        c = _cert()
        self.client.post(reverse("sistema_gestione:esterni_certificazione_documento_carica", args=[c.pk]),
                         {"file": SimpleUploadedFile("x.exe", b"MZ", "application/octet-stream")})
        self.assertFalse(c.documenti.exists())

    def test_documento_di_un_altro_certificato_non_si_apre(self):
        a, b = _cert(), _cert(norma="ISO45001")
        d = CertificazioneDocumento.objects.create(certificazione=a, nome="c.pdf", sha256="0" * 64, file="x.pdf")
        r = self.client.get(reverse("sistema_gestione:esterni_certificazione_documento", args=[b.pk, d.pk]))
        self.assertEqual(r.status_code, 404)

    def test_chi_non_ha_permessi_non_apre_la_scheda(self):
        c = _cert()
        self.client.force_login(get_user_model().objects.create_user("sgi_no", password="x"))
        r = self.client.get(reverse("sistema_gestione:esterni_certificazione_scheda", args=[c.pk]))
        self.assertIn(r.status_code, (302, 403))
        self.assertNotIn(b"Ente Prova", r.content)

    def test_salvando_si_tengono_le_qualifiche_collegate(self):
        t = TipoQualifica.objects.create(nome="Prova collegata")
        r = self.client.post(reverse("sistema_gestione:esterni_certificazione_nuova"), {
            "norma": "EN9100", "ente": "Ente Prova", "scade_il": "2031-01-01", "attiva": "on",
            "qualifiche_richieste": [t.pk]})
        c = Certificazione.objects.get()
        self.assertRedirects(r, reverse("sistema_gestione:esterni_certificazione_scheda", args=[c.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(list(c.qualifiche_richieste.all()), [t])

    def test_audit_collegato_in_scheda(self):
        c = _cert()
        AuditEsterno.objects.create(tipo="SORVEGLIANZA", ente="Ente Prova", certificazione=c, en9100=True,
                                    data_inizio=timezone.localdate())
        html = self.client.get(reverse("sistema_gestione:esterni_certificazione_scheda", args=[c.pk])).content.decode()
        self.assertIn("Sorveglianza", html)


class CollegamentoFormazioneTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.tipo = TipoQualifica.objects.create(nome="Auditor interno prova")
        self.oggi = timezone.localdate()

    def _qualifica(self, legacy, giorni, **kw):
        return DipendenteQualifica.objects.create(
            legacy_anagrafica_id=legacy, tipo=self.tipo, data_conseguimento=self.oggi - timedelta(days=100),
            data_scadenza=self.oggi + timedelta(days=giorni) if giorni is not None else None, **kw)

    def test_copertura_conta_una_persona_per_stato(self):
        self._qualifica(9001, 200)
        self._qualifica(9002, 30)
        self._qualifica(9003, -5)
        self._qualifica(9004, None)
        riga = copertura_qualifiche([self.tipo])[0]
        self.assertEqual((riga["valide"], riga["in_scadenza"], riga["scadute"]), (2, 1, 1))

    def test_qualifica_rinnovata_non_conta_la_vecchia(self):
        DipendenteQualifica.objects.create(legacy_anagrafica_id=9001, tipo=self.tipo,
                                           data_conseguimento=self.oggi - timedelta(days=900),
                                           data_scadenza=self.oggi - timedelta(days=500))
        self._qualifica(9001, 200)
        riga = copertura_qualifiche([self.tipo])[0]
        self.assertEqual((riga["valide"], riga["scadute"]), (1, 0))

    def _auditor(self):
        return Auditor.objects.create(interno=True, user=self.su, req_diploma=True, req_norme=True,
                                      req_tecniche_audit=True, req_settore=True, req_esperienza_2_anni=True,
                                      requisiti_verificati_il=self.oggi, audit_svolti_pregressi=4)

    def test_senza_collegamento_conta_solo_la_data_a_mano(self):
        auditor = self._auditor()
        self.assertIsNone(auditor.qualifica_formazione)
        self.assertTrue(auditor.qualificato)

    def test_qualifica_scaduta_in_formazione_toglie_la_qualifica(self):
        SiteConfig.set(CHIAVE_TIPO_AUDITOR, str(self.tipo.pk), "prova")
        self._qualifica(9001, -1)
        with patch("sistema_gestione.services.qualifiche.get_legacy_anagrafica_id", return_value=9001):
            auditor = self._auditor()
            self.assertTrue(auditor.qualifica_formazione["scaduta"])
            self.assertFalse(auditor.qualificato)

    def test_qualifica_non_registrata_avvisa_ma_non_blocca(self):
        SiteConfig.set(CHIAVE_TIPO_AUDITOR, str(self.tipo.pk), "prova")
        with patch("sistema_gestione.services.qualifiche.get_legacy_anagrafica_id", return_value=9001):
            auditor = self._auditor()
            self.assertFalse(auditor.qualifica_formazione["trovata"])
            self.assertTrue(auditor.qualificato)

    def test_elenco_auditor_e_impostazioni(self):
        r = self.client.get(reverse("sistema_gestione:audit_impostazioni"))
        self.assertContains(r, "Auditor interno prova")
        SiteConfig.set(CHIAVE_TIPO_AUDITOR, str(self.tipo.pk), "prova")
        self._qualifica(9001, 10)
        self._auditor()
        with patch("sistema_gestione.services.qualifiche.get_legacy_anagrafica_id", return_value=9001):
            r = self.client.get(reverse("sistema_gestione:auditor_elenco"))
        self.assertContains(r, "Qualifica in Formazione")
        self.assertContains(r, "Scade il")

    def test_scadute_dei_certificati_nel_da_fare(self):
        c = _cert()
        c.qualifiche_richieste.add(self.tipo)
        self._qualifica(9001, -3)
        voci = panoramica.da_fare(self.oggi)
        self.assertTrue(any("Auditor interno prova" in v["testo"] and "scadute 1" in v["testo"] for v in voci))


class RiesameTests(BaseTest):
    def test_report_nel_pacchetto_riesame(self):
        c = _cert(scade_il=timezone.localdate() + timedelta(days=30))
        AuditEsterno.objects.create(tipo="SORVEGLIANZA", ente="Ente Prova", certificazione=c, en9100=True,
                                    data_inizio=timezone.localdate())
        definizione = get_report("certificazioni-audit-esterni")
        oggi = timezone.localdate()
        risultato = definizione.builder(ReportParams(date_from=oggi - timedelta(days=30), date_to=oggi + timedelta(days=1),
                                                     today=oggi))
        valori = {k.label: k.value for k in risultato.kpis}
        self.assertEqual(valori["Certificati in vigore"], 1)
        self.assertEqual(valori["Scaduti o in scadenza (90 giorni)"], 1)
        self.assertEqual(valori["Audit esterni nel periodo"], 1)
        self.assertEqual(len(risultato.rows), 1)


class TemplateBilanciatiTests(TestCase):
    def test_nelle_pagine_del_modulo_i_div_si_chiudono_tutti(self):
        """Un </div> in più in «Audit interni» faceva uscire le sezioni dal contenitore della pagina."""
        cartella = Path(__file__).parent / "templates" / "sistema_gestione" / "pages"
        for nome in ("index", "audit_index", "esterni_elenco", "esterni_certificazione_scheda", "riesame_elenco", "riesame_dettaglio"):
            testo = (cartella / f"{nome}.html").read_text(encoding="utf-8")
            with self.subTest(pagina=nome):
                self.assertEqual(len(re.findall(r"<div\b", testo)), testo.count("</div>"))

