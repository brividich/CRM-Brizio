"""Pagine d'ingresso delle sezioni di Anagrafica nello stile C: una scheda per oggetto.

Persone (reparto), Ingressi (posizione aperta), Qualifiche (tipo), Salute e
sicurezza (mansione di rischio), Visite (tipo di visita), Amministrazione (flusso
di import), Report (modello). Le schede leggono gli stessi dati dei numeri in alto
della pagina: qui si verifica che i conteggi tornino, che i collegamenti puntino
alla pagina giusta e che le visite non mostrino mai un esito. Dati sintetici.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    DipendenteAnagraficaAziendale,
    DipendenteQualifica,
    ImportazioneRetributiva,
    Mansione,
    TipologiaContratto,
    TipoQualifica,
    TipoVisitaMedica,
    VisitaMedica,
)
from .models_recruiting import Candidato, PosizioneAperta
from .models_reportistica import ReportModello
from .services import sezioni_c
from .tests import _ensure_anagrafica_table
from .tests_exports_persone import _insert_dipendente

User = get_user_model()


class ServizioSchedeTests(TestCase):
    def test_segmenti_sommano_a_cento_e_saltano_i_vuoti(self):
        segs, tot = sezioni_c.segmenti([("ok", 3), ("ko", 0), ("mai", 1)])
        self.assertEqual(tot, 4)
        self.assertEqual([s["chiave"] for s in segs], ["ok", "mai"])
        self.assertAlmostEqual(sum(s["perc"] for s in segs), 100, delta=0.1)
        self.assertEqual(sezioni_c.segmenti([("ok", 0)]), ([], 0))

    def test_le_etichette_di_filtro_non_hanno_spazi(self):
        self.assertEqual(sezioni_c.tag_slug("UNI/PdR 125"), "uni-pdr-125")
        cc = sezioni_c.griglia(id="x", titolo="t", icona="i", aside="", schede=[],
                               filtri=[("", "Tutte"), ("ISO 9001", "ISO 9001")])
        self.assertEqual(cc["filtri"], [("", "Tutte"), ("iso-9001", "ISO 9001")])

    def test_qualifiche_classificate_come_i_numeri_del_cruscotto(self):
        oggi = timezone.localdate()
        tipo = SimpleNamespace(pk=1, nome="Carrellista", categoria="SICUREZZA", durata_mesi=60,
                               get_categoria_display=lambda: "Sicurezza")
        q = lambda d, doc="", ver=True: SimpleNamespace(tipo_id=1, tipo=tipo, data_scadenza=d, documento=doc, verificata=ver)
        quals = [q(None), q(oggi + timedelta(days=200)), q(oggi + timedelta(days=45)),
                 q(oggi + timedelta(days=10)), q(oggi - timedelta(days=1), doc="x", ver=False)]
        [s] = sezioni_c.schede_qualifiche(quals, oggi=oggi, soglia_30=oggi + timedelta(days=30),
                                          soglia_60=oggi + timedelta(days=60), prossime_per_tipo={})
        conteggi = {seg["chiave"]: seg["n"] for seg in s["segmenti"]}
        self.assertEqual(conteggi, {"ok": 2, "s90": 1, "s30": 1, "ko": 1})
        self.assertEqual(s["principale"], "5")
        self.assertIn("1 da verificare", [p["testo"] for p in s["pillole"]])
        self.assertIn("?tipo=1&stato=tutte", s["href"])

    def test_reparti_raggruppano_per_contratto(self):
        rows = [{"id": 1, "reparto": "Saldatura"}, {"id": 2, "reparto": "Saldatura"}, {"id": 3, "reparto": ""}]
        schede, legenda = sezioni_c.schede_reparti(rows, {1: "IND", 2: "", 3: "IND"}, {"IND": "Indeterminato"},
                                                   reparto_attivo="saldatura")
        sald = next(s for s in schede if s["titolo"] == "Saldatura")
        self.assertEqual(sald["principale"], "2")
        self.assertTrue(sald["attiva"])
        self.assertEqual({seg["chiave"]: seg["n"] for seg in sald["segmenti"]}, {"nv": 1, "mai": 1})
        self.assertIn(("nv", "Indeterminato"), legenda)
        senza = next(s for s in schede if s["titolo"] == "Senza reparto")
        self.assertEqual(senza["href"], "")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PagineSezioniTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser("sez_c_admin", "sez_c@example.invalid", "x")

    def setUp(self):
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()

    def test_persone_una_scheda_per_reparto_che_filtra_l_elenco(self):
        a = _insert_dipendente(8101, "Mario", "Rossi", reparto="SALDATURA", mansione="Saldatore")
        _insert_dipendente(8102, "Anna", "Verdi", reparto="SALDATURA", mansione="Saldatrice")
        TipologiaContratto.objects.get_or_create(codice="IND", defaults={"nome": "Indeterminato"})
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=a, tipologia_contratto="IND")
        r = self.client.get(reverse("anagrafica:dipendenti_list"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="fmd-reparti"')
        self.assertContains(r, "?reparto=SALDATURA&amp;vf=0")
        self.assertContains(r, "Indeterminato")
        self.assertNotContains(r, "{#")

    def test_qualifiche_una_scheda_per_tipo(self):
        tipo = TipoQualifica.objects.create(nome="Patentino TIG", categoria=TipoQualifica.CAT_PROFESSIONALE, durata_mesi=24)
        DipendenteQualifica.objects.create(legacy_anagrafica_id=8201, tipo=tipo, data_scadenza=self.oggi - timedelta(days=3))
        DipendenteQualifica.objects.create(legacy_anagrafica_id=8202, tipo=tipo, data_scadenza=self.oggi + timedelta(days=300))
        r = self.client.get(reverse("anagrafica:qualifiche_dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="fmd-qualifiche"')
        self.assertContains(r, f"{reverse('anagrafica:qualifiche_scadenzario')}?tipo={tipo.pk}&amp;stato=tutte")
        self.assertContains(r, "1 scaduta")
        self.assertContains(r, 'data-cc-filtro="professionale"')

    def test_visite_schede_per_tipo_senza_esiti(self):
        tipo = TipoVisitaMedica.objects.create(nome="Periodica rumore", durata_mesi=12, obbligatoria=True)
        VisitaMedica.objects.create(legacy_anagrafica_id=8301, tipo=tipo, data_svolgimento=self.oggi - timedelta(days=400),
                                    data_scadenza=self.oggi - timedelta(days=35),
                                    esito=VisitaMedica.Esito.IDONEO_CON_LIMITAZIONI)
        r = self.client.get(reverse("anagrafica:visite_mediche_dashboard"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        griglia = html.split('id="fmd-visite"', 1)[1].split("</section>", 1)[0]
        self.assertIn(f"#tipo-row-{tipo.pk}", griglia)
        self.assertIn("1 scaduta", griglia)
        self.assertNotIn("limitazioni", griglia.lower())
        self.assertContains(r, "Referti da rivedere")

    def test_sicurezza_una_scheda_per_mansione_di_rischio(self):
        # Spec Mansionario 15/10/2026: le schede sono le voci del catalogo Mansione.
        m = Mansione.objects.create(nome="ADDETTO SALDATURA SINTETICO", livello_rischio="A")
        r = self.client.get(reverse("anagrafica:sicurezza_hub"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="fmd-mansioni-rischio"')
        self.assertContains(r, reverse("anagrafica:mansione_requisiti", args=[m.pk]))
        self.assertContains(r, "Rischio alto")

    def test_ingressi_una_scheda_per_posizione_con_i_candidati_per_fase(self):
        p = PosizioneAperta.objects.create(titolo="Saldatore TIG", reparto="SALDATURA", posti=2,
                                           data_richiesta=self.oggi - timedelta(days=40),
                                           entro_il=self.oggi - timedelta(days=5))
        Candidato.objects.create(posizione=p, stato=Candidato.STATO_COLLOQUIO_1)
        Candidato.objects.create(posizione=p, stato=Candidato.STATO_NUOVO)
        Candidato.objects.create(posizione=p, stato=Candidato.STATO_SCARTATO)
        r = self.client.get(reverse("anagrafica:recruiting_dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="fmd-posizioni"')
        self.assertContains(r, reverse("anagrafica:recruiting_posizione_detail", args=[p.pk]))
        self.assertContains(r, 'data-cc-filtro="ritardo"')
        self.assertContains(r, "<b>2</b> candidati")  # lo scartato è uscito dall'iter

    def test_cedolini_solo_cedolini(self):
        ImportazioneRetributiva.objects.create(data_competenza=self.oggi.replace(day=1), righe_ok=12, righe_errore=2,
                                               file_nome="sintetico.csv")
        r = self.client.get(reverse("anagrafica:retribuzioni_globale"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Righe dell'ultimo import")
        self.assertContains(r, 'id="importazione"')
        # Contratti, ferie e scadenze stanno nelle loro pagine.
        self.assertNotContains(r, 'id="fmd-import"')
        self.assertNotContains(r, "Contratti e periodi di prova in scadenza")
        self.assertNotContains(r, "Contratti in scadenza")

    def test_report_una_scheda_per_modello_con_le_azioni(self):
        m = ReportModello.objects.create(nome="Organico sintetico", titolo_documento="Organico", norme=["ISO 9001"])
        r = self.client.get(reverse("anagrafica:reportistica_index"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="fmd-modelli"')
        self.assertContains(r, reverse("anagrafica:reportistica_genera", args=[m.pk]))
        self.assertContains(r, reverse("anagrafica:reportistica_modello_duplica", args=[m.pk]))
        self.assertContains(r, 'data-cc-filtro="iso-9001"')
