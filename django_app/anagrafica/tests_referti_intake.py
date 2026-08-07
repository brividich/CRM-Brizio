"""Acquisizione automatica dei referti di sorveglianza sanitaria.

ADR: docs/superpowers/specs/2026-08-06-sorveglianza-sanitaria-intake-referti-design.md

I testi usati qui riproducono il **layout** di un certificato Winasped, compresi
gli errori tipici dell'OCR misurati su una scansione reale (data corrotta,
cognome storpiato dalla firma autografa sovrapposta, bordi di tabella letti come
caratteri). I dati sono inventati: nessun nome, nessuna data di nascita e nessun
giudizio reale entra in una fixture.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import TipoVisitaMedica, VisitaMedica
from .models_sorveglianza import (
    AliasEsameProtocollo,
    AliasEsitoIdoneita,
    RefertoIntakeConfig,
    RefertoIntakeRiga,
)
from .services.referti_match import cerca_dipendente, somiglianza
from .services.referti_parsing import analizza_testo, normalizza, pare_certificato
from .services.referti_registrazione import (
    ErroreRegistrazione,
    prepara_registrazione,
    registra,
)

User = get_user_model()


# Layout autentico, contenuti inventati. Le due colonne del protocollo arrivano
# appaiate per riga, come le rende Tesseract con la segmentazione a blocco.
CERTIFICATO = """Dr Mario Esempio
Specialista in Medicina del Lavoro
Azienda AZIENDA DI PROVA SRL
Settore METALMECCANICO
N.Cartella 1234 N.Matricola N.interno 1234
Sesso M Data Nascita 11-04-1975 VERDI GIUSEPPE
Comune Nascita CITTA DI PROVA (XX) VIA INVENTATA, 1
CERTIFICATO MEDICO DI IDONEITA' ALLA MANSIONE
Mansione ADD. PROVA
Dt.assunzione 01-02-2000
Data inizio mansione 01-02-2000
RISCHI LAVORAZIONE
Agenti Chimici
PROTOCOLLO SANITARIO
Esame/prestazione Periodicita'
Visita Medica annuale
Visita Oculistica biennale
GIUDIZIO DI IDONEITA' (Espresso il 15-03-2024)
Trasmesso al datore di lavoro il..15-03-2024 a mezzo:consegna a mano
Trasmesso al lavoratore il..15-03-2024
IDONEO MANSIONE SPECIFICA
(ai sensi dell'art.41 D.Lgs 81/2008)
Il Lavoratore VERDI GIUSEPPE: /
Winasped 4.1.21 - Certificato di idoneita'
"""


class ParsingTests(TestCase):
    """Estrazione dei campi dal testo, compresi i casi con rumore OCR."""

    def test_estrae_tutti_i_campi_dal_layout_completo(self):
        campi = analizza_testo(CERTIFICATO)
        self.assertTrue(campi.e_certificato)
        self.assertEqual(campi.nominativo, "VERDI GIUSEPPE")
        self.assertFalse(campi.nominativo_da_ripiego)
        self.assertEqual(campi.data_nascita, date(1975, 4, 11))
        self.assertEqual(campi.data_giudizio, date(2024, 3, 15))
        self.assertEqual(campi.esito_testo, "IDONEO MANSIONE SPECIFICA")
        self.assertEqual(campi.mansione, "ADD. PROVA")
        self.assertEqual(len(campi.protocollo), 2)
        self.assertTrue(campi.minimo_utile)

    def test_protocollo_appaia_esame_e_periodicita(self):
        campi = analizza_testo(CERTIFICATO)
        coppie = {v["esame"]: v["periodicita"] for v in campi.protocollo}
        self.assertEqual(coppie["Visita Medica"], "annuale")
        self.assertEqual(coppie["Visita Oculistica"], "biennale")

    def test_data_del_giudizio_recuperata_per_consenso_quando_una_e_corrotta(self):
        """L'errore misurato davvero: «Espresso il 241-03-2024».

        Il pattern singolo scarterebbe il referto per una cifra. Le altre due
        occorrenze concordano, e la data si ricostruisce.
        """
        rovinato = CERTIFICATO.replace("Espresso il 15-03-2024", "Espresso il 241-03-2024")
        campi = analizza_testo(rovinato)
        self.assertEqual(campi.data_giudizio, date(2024, 3, 15))

    def test_data_ricucita_quando_l_ocr_spezza_la_riga(self):
        spezzato = CERTIFICATO.replace(
            "Trasmesso al lavoratore il..15-03-2024",
            "Trasmesso al lavoratore il..15-03-\n2024",
        )
        campi = analizza_testo(spezzato)
        self.assertEqual(campi.data_giudizio, date(2024, 3, 15))

    def test_ripiego_sulla_riga_di_firma_viene_dichiarato(self):
        """Senza blocco anagrafico si ripiega sulla firma, ma lo si dice.

        È il caso che ha prodotto un nome verosimile e sbagliato in prova: la
        dichiarazione è ciò che impedisce a valle di fidarsene.
        """
        senza_blocco = CERTIFICATO.replace(
            "Sesso M Data Nascita 11-04-1975 VERDI GIUSEPPE",
            "Sesso M",
        )
        campi = analizza_testo(senza_blocco)
        self.assertEqual(campi.nominativo, "VERDI GIUSEPPE")
        self.assertTrue(campi.nominativo_da_ripiego)

    def test_bordi_di_tabella_non_si_attaccano_al_nome_dell_esame(self):
        sporco = CERTIFICATO.replace(
            "Visita Oculistica biennale", "| \\Visita Oculistica [=] biennale"
        )
        campi = analizza_testo(sporco)
        nomi = [v["esame"] for v in campi.protocollo]
        self.assertIn("Visita Oculistica", nomi)

    def test_documento_estraneo_non_viene_scambiato_per_certificato(self):
        campi = analizza_testo("Fattura n. 12 del 03-03-2024\nTotale 100 euro\n")
        self.assertFalse(campi.e_certificato)
        self.assertFalse(campi.minimo_utile)

    def test_testo_vuoto_non_solleva(self):
        campi = analizza_testo("")
        self.assertFalse(campi.e_certificato)
        self.assertEqual(campi.nominativo, "")

    def test_periodicita_senza_esame_accanto_non_viene_indovinata(self):
        """Colonne separate: la cadenza da sola non dice a quale esame appartiene."""
        separato = CERTIFICATO.replace(
            "Visita Medica annuale\nVisita Oculistica biennale",
            "Visita Medica\nVisita Oculistica\nannuale\nbiennale",
        )
        campi = analizza_testo(separato)
        self.assertEqual(campi.protocollo, [])

    def test_normalizza_ignora_accenti_e_maiuscole(self):
        self.assertEqual(normalizza("Visita Medica"), normalizza("VISITA  MEDICA"))
        self.assertEqual(normalizza("però"), "PERO")

    def test_pare_certificato_basta_una_impronta(self):
        self.assertTrue(pare_certificato("... PROTOCOLLO SANITARIO ..."))
        self.assertFalse(pare_certificato("Una lettera qualunque"))


class SomiglianzaTests(TestCase):
    def test_identici(self):
        self.assertEqual(somiglianza("VERDI GIUSEPPE", "Verdi Giuseppe"), 100)

    def test_ordine_invertito_resta_alto(self):
        self.assertGreaterEqual(somiglianza("VERDI GIUSEPPE", "Giuseppe Verdi"), 95)

    def test_cognome_storpiato_scende_ma_non_crolla(self):
        punteggio = somiglianza("VERDII GIUSEPPE", "Verdi Giuseppe")
        self.assertGreater(punteggio, 80)
        self.assertLess(punteggio, 100)

    def test_persone_diverse_restano_basse(self):
        self.assertLess(somiglianza("VERDI GIUSEPPE", "Rossi Anna"), 60)

    def test_stringa_vuota(self):
        self.assertEqual(somiglianza("", "Verdi Giuseppe"), 0)


def _anagrafica(righe):
    """Sostituisce la lettura dell'anagrafica legacy con un elenco noto."""
    return patch(
        "anagrafica.services.referti_match._righe_anagrafica", return_value=righe
    )


def _nascite(mappa):
    return patch(
        "anagrafica.services.referti_match._anagrafica_civile", return_value=mappa
    )


class MatchTests(TestCase):
    """Il riconoscimento del dipendente e i casi in cui si rifiuta di decidere."""

    def setUp(self):
        self.config = RefertoIntakeConfig.load()
        self.tizio = {"legacy_id": 10, "nominativo": "VERDI GIUSEPPE", "cessato": False}
        self.caio = {"legacy_id": 20, "nominativo": "ROSSI ANNA", "cessato": False}

    def test_data_di_nascita_coincidente_conferma_anche_col_nome_storpiato(self):
        with _anagrafica([self.tizio, self.caio]), _nascite({10: date(1975, 4, 11)}):
            esito = cerca_dipendente("VERDII GIUSEPP", date(1975, 4, 11), config=self.config)
        self.assertTrue(esito.automatico)
        self.assertEqual(esito.legacy_id, 10)
        self.assertTrue(esito.scelto.conferma_data_nascita)

    def test_data_di_nascita_discordante_manda_sempre_in_revisione(self):
        """Anche con nome identico: la data smentisce, e la smentita vince."""
        with _anagrafica([self.tizio]), _nascite({10: date(1980, 1, 1)}):
            esito = cerca_dipendente("VERDI GIUSEPPE", date(1975, 4, 11), config=self.config)
        self.assertFalse(esito.automatico)
        self.assertIn("data di nascita", esito.motivo.lower())

    def test_senza_data_di_nascita_serve_somiglianza_alta(self):
        with _anagrafica([self.tizio]), _nascite({}):
            esito = cerca_dipendente("VERDI GIUSEPPE", None, config=self.config)
        self.assertTrue(esito.automatico)

    def test_senza_data_di_nascita_somiglianza_media_non_basta(self):
        with _anagrafica([self.tizio]), _nascite({}):
            esito = cerca_dipendente("VERDONI GIUSEPPA", None, config=self.config)
        self.assertFalse(esito.automatico)

    def test_omonimi_con_stessa_data_di_nascita_vanno_scelti_a_mano(self):
        gemello = {"legacy_id": 11, "nominativo": "VERDI GIUSEPPE", "cessato": False}
        with _anagrafica([self.tizio, gemello]), \
                _nascite({10: date(1975, 4, 11), 11: date(1975, 4, 11)}):
            esito = cerca_dipendente("VERDI GIUSEPPE", date(1975, 4, 11), config=self.config)
        self.assertFalse(esito.automatico)
        self.assertEqual(len(esito.candidati), 2)

    def test_due_candidati_ugualmente_somiglianti_senza_data(self):
        gemello = {"legacy_id": 11, "nominativo": "VERDI GIUSEPPE", "cessato": False}
        with _anagrafica([self.tizio, gemello]), _nascite({}):
            esito = cerca_dipendente("VERDI GIUSEPPE", None, config=self.config)
        self.assertFalse(esito.automatico)

    def test_dipendente_cessato_non_si_conferma_da_solo(self):
        uscito = {"legacy_id": 10, "nominativo": "VERDI GIUSEPPE", "cessato": True}
        with _anagrafica([uscito]), _nascite({10: date(1975, 4, 11)}):
            esito = cerca_dipendente("VERDI GIUSEPPE", date(1975, 4, 11), config=self.config)
        self.assertFalse(esito.automatico)
        self.assertIn("cessato", esito.motivo.lower())
        self.assertEqual(esito.legacy_id, 10)  # lo trova comunque

    def test_nominativo_da_ripiego_non_si_conferma_mai(self):
        with _anagrafica([self.tizio]), _nascite({10: date(1975, 4, 11)}):
            esito = cerca_dipendente(
                "VERDI GIUSEPPE", date(1975, 4, 11), da_ripiego=True, config=self.config
            )
        self.assertFalse(esito.automatico)
        self.assertIn("firma", esito.motivo.lower())

    def test_nessun_candidato(self):
        with _anagrafica([self.caio]), _nascite({}):
            esito = cerca_dipendente("BIANCHI CARLO", None, config=self.config)
        self.assertIsNone(esito.scelto)
        self.assertFalse(esito.automatico)

    def test_nominativo_vuoto(self):
        esito = cerca_dipendente("", None, config=self.config)
        self.assertIsNone(esito.scelto)


class RegistrazioneTests(TestCase):
    """Dalla lettura alle visite: N visite, periodicità dal catalogo, atomicità."""

    def setUp(self):
        self.medica = TipoVisitaMedica.objects.create(nome="Visita Medica", durata_mesi=12)
        self.oculistica = TipoVisitaMedica.objects.create(nome="Visita Oculistica", durata_mesi=24)
        AliasEsitoIdoneita.objects.create(
            testo="IDONEO MANSIONE SPECIFICA", esito=VisitaMedica.Esito.IDONEO_MANSIONE
        )
        self.utente = User.objects.create_user("revisore", password="x")

    def _riga(self, **extra):
        campi = {
            "nome_file": "referto.pdf",
            "sha256": "a" * 64,
            "letto_nominativo": "VERDI GIUSEPPE",
            "letto_data_giudizio": date(2024, 3, 15),
            "letto_esito_testo": "IDONEO MANSIONE SPECIFICA",
            "letto_protocollo": [
                {"esame": "Visita Medica", "periodicita": "annuale"},
                {"esame": "Visita Oculistica", "periodicita": "biennale"},
            ],
            "legacy_anagrafica_id_proposto": 10,
            "esito": RefertoIntakeRiga.ESITO_DA_RIVEDERE,
        }
        campi.update(extra)
        return RefertoIntakeRiga.objects.create(**campi)

    def test_un_certificato_genera_una_visita_per_esame(self):
        create = registra(self._riga(), utente=self.utente)
        self.assertEqual(len(create), 2)
        self.assertEqual(VisitaMedica.objects.filter(legacy_anagrafica_id=10).count(), 2)

    def test_la_scadenza_viene_dal_catalogo_non_dal_certificato(self):
        registra(self._riga(), utente=self.utente)
        medica = VisitaMedica.objects.get(tipo=self.medica)
        oculistica = VisitaMedica.objects.get(tipo=self.oculistica)
        self.assertEqual(medica.data_scadenza, date(2025, 3, 15))    # 12 mesi
        self.assertEqual(oculistica.data_scadenza, date(2026, 3, 15))  # 24 mesi

    def test_periodicita_divergente_non_blocca_ma_viene_segnalata(self):
        """Il medico dichiara una cadenza diversa: vince il catalogo, ma si dice."""
        self.oculistica.durata_mesi = 36
        self.oculistica.save()
        riga = self._riga()
        registra(riga, utente=self.utente)
        riga.refresh_from_db()
        self.assertTrue(riga.divergenze)
        divergenza = riga.divergenze[0]
        self.assertEqual(divergenza["certificato_mesi"], 24)
        self.assertEqual(divergenza["catalogo_mesi"], 36)
        # La scadenza resta quella del catalogo.
        self.assertEqual(
            VisitaMedica.objects.get(tipo=self.oculistica).data_scadenza, date(2027, 3, 15)
        )

    def test_il_referto_e_uno_solo_e_condiviso_da_tutte_le_visite(self):
        create = registra(self._riga(), utente=self.utente)
        documenti = {v.referto_documento_id for v in create}
        self.assertEqual(len(documenti), 1)

    def test_esame_fuori_catalogo_ferma_tutto_senza_inventare_il_tipo(self):
        riga = self._riga(letto_protocollo=[
            {"esame": "Visita Medica", "periodicita": "annuale"},
            {"esame": "Esame Mai Visto", "periodicita": "annuale"},
        ])
        with self.assertRaises(ErroreRegistrazione):
            registra(riga, utente=self.utente)
        # Atomicità: nessuna visita creata, nemmeno quella riconosciuta.
        self.assertEqual(VisitaMedica.objects.count(), 0)

    def test_giudizio_non_mappato_ferma_la_registrazione(self):
        riga = self._riga(letto_esito_testo="IDONEO CON QUALCOSA DI NUOVO")
        with self.assertRaises(ErroreRegistrazione):
            registra(riga, utente=self.utente)
        self.assertEqual(VisitaMedica.objects.count(), 0)

    def test_senza_data_del_giudizio_non_si_registra(self):
        riga = self._riga(letto_data_giudizio=None)
        with self.assertRaises(ErroreRegistrazione):
            registra(riga, utente=self.utente)

    def test_senza_dipendente_non_si_registra(self):
        riga = self._riga(legacy_anagrafica_id_proposto=None)
        with self.assertRaises(ErroreRegistrazione):
            registra(riga, utente=self.utente)

    def test_doppione_logico_non_crea_una_seconda_volta(self):
        registra(self._riga(), utente=self.utente)
        with self.assertRaises(ErroreRegistrazione):
            registra(self._riga(sha256="b" * 64), utente=self.utente)
        self.assertEqual(VisitaMedica.objects.count(), 2)

    def test_registrazione_parziale_quando_solo_un_tipo_e_gia_presente(self):
        VisitaMedica.objects.create(
            legacy_anagrafica_id=10, tipo=self.medica, data_svolgimento=date(2024, 3, 15)
        )
        create = registra(self._riga(), utente=self.utente)
        self.assertEqual(len(create), 1)
        self.assertEqual(create[0].tipo, self.oculistica)

    def test_traccia_di_chi_ha_confermato(self):
        riga = self._riga()
        registra(riga, utente=self.utente)
        riga.refresh_from_db()
        self.assertEqual(riga.confermato_da, self.utente)
        self.assertIsNotNone(riga.confermato_il)
        self.assertEqual(riga.esito, RefertoIntakeRiga.ESITO_OK)
        self.assertEqual(riga.visite_create, 2)

    def test_alias_permette_un_nome_che_il_catalogo_non_ha(self):
        AliasEsameProtocollo.objects.create(testo="Vis. medica periodica", tipo=self.medica)
        riga = self._riga(letto_protocollo=[
            {"esame": "Vis. medica periodica", "periodicita": "annuale"},
        ])
        create = registra(riga, utente=self.utente)
        self.assertEqual(len(create), 1)
        self.assertEqual(create[0].tipo, self.medica)

    def test_prepara_registrazione_non_scrive_nulla(self):
        campi = analizza_testo(CERTIFICATO)
        piano = prepara_registrazione(campi)
        self.assertEqual(len(piano.tipi), 2)
        self.assertEqual(piano.esito, VisitaMedica.Esito.IDONEO_MANSIONE)
        self.assertEqual(VisitaMedica.objects.count(), 0)


@override_settings(LEGACY_AUTH_ENABLED=False)
class PermessiTests(TestCase):
    """Le pagine dei referti sono chiuse a chi non tratta dati sanitari."""

    def setUp(self):
        self.chiunque = User.objects.create_user("passante", password="x")
        self.ammesso = User.objects.create_superuser("capo", "capo@example.invalid", "x")

    def _rotte(self):
        return [
            "/anagrafica/visite-mediche/referti/",
            "/anagrafica/visite-mediche/referti/registro/",
            "/anagrafica/visite-mediche/referti/impostazioni/",
        ]

    def test_utente_senza_permesso_viene_respinto(self):
        self.client.force_login(self.chiunque)
        for rotta in self._rotte():
            with self.subTest(rotta=rotta):
                risposta = self.client.get(rotta)
                self.assertEqual(risposta.status_code, 302)
                self.assertNotIn("referti", risposta["Location"])

    def test_utente_autorizzato_entra(self):
        self.client.force_login(self.ammesso)
        for rotta in self._rotte():
            with self.subTest(rotta=rotta):
                self.assertEqual(self.client.get(rotta).status_code, 200)

    def test_anonimo_va_al_login(self):
        risposta = self.client.get("/anagrafica/visite-mediche/referti/")
        self.assertEqual(risposta.status_code, 302)
        self.assertIn("login", risposta["Location"].lower())

    def test_conferma_richiede_post(self):
        self.client.force_login(self.ammesso)
        riga = RefertoIntakeRiga.objects.create(nome_file="x.pdf")
        risposta = self.client.get(f"/anagrafica/visite-mediche/referti/{riga.pk}/conferma/")
        self.assertEqual(risposta.status_code, 405)

    def test_scarto_non_cancella_la_riga(self):
        self.client.force_login(self.ammesso)
        riga = RefertoIntakeRiga.objects.create(
            nome_file="x.pdf", esito=RefertoIntakeRiga.ESITO_DA_RIVEDERE
        )
        self.client.post(
            f"/anagrafica/visite-mediche/referti/{riga.pk}/scarta/", {"motivo": "non serve"}
        )
        riga.refresh_from_db()
        self.assertEqual(riga.esito, RefertoIntakeRiga.ESITO_SCARTATO)
        self.assertEqual(riga.messaggio, "non serve")


class ConfigTests(TestCase):
    def test_singleton(self):
        a = RefertoIntakeConfig.load()
        b = RefertoIntakeConfig.load()
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(RefertoIntakeConfig.objects.count(), 1)

    def test_default_prudenti(self):
        config = RefertoIntakeConfig.load()
        self.assertFalse(config.attiva)
        self.assertFalse(config.conferma_automatica)

    def test_parametri_ocr_misurati_non_canonici(self):
        """200 dpi e psm 6: i default canonici corrompevano la data del giudizio."""
        config = RefertoIntakeConfig.load()
        self.assertEqual(config.ocr_dpi, 200)
        self.assertEqual(config.ocr_psm, 6)

    def test_soglia_senza_data_deve_essere_almeno_pari_a_quella_con_data(self):
        from .forms import RefertoIntakeConfigForm

        form = RefertoIntakeConfigForm(data={
            "attiva": False, "cartella": "", "sposta_elaborati": True,
            "max_file_per_giro": 25, "ocr_dpi": 200, "ocr_psm": 6,
            "ocr_lingua": "ita", "ocr_timeout_secondi": 30,
            "soglia_con_data_nascita": 95, "soglia_senza_data_nascita": 70,
            "conferma_automatica": False,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("soglia_senza_data_nascita", form.errors)

    def test_attiva_senza_cartella_non_passa(self):
        from .forms import RefertoIntakeConfigForm

        form = RefertoIntakeConfigForm(data={
            "attiva": True, "cartella": "  ", "sposta_elaborati": True,
            "max_file_per_giro": 25, "ocr_dpi": 200, "ocr_psm": 6,
            "ocr_lingua": "ita", "ocr_timeout_secondi": 30,
            "soglia_con_data_nascita": 70, "soglia_senza_data_nascita": 92,
            "conferma_automatica": False,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("cartella", form.errors)


class IntakeTests(TestCase):
    """Il giro sulla cartella e l'idempotenza."""

    def test_cartella_spenta_non_fa_nulla(self):
        from .services.referti_intake import elabora_cartella

        esito = elabora_cartella()
        self.assertEqual(esito["esaminati"], 0)
        self.assertIn("spenta", esito["riepilogo"].lower())

    def test_cartella_irraggiungibile_non_solleva(self):
        from .services.referti_intake import elabora_cartella

        config = RefertoIntakeConfig.load()
        config.attiva = True
        config.cartella = r"\\server-che-non-esiste\referti"
        config.save()
        esito = elabora_cartella(config)
        self.assertEqual(esito["esaminati"], 0)
        self.assertIn("non raggiungibile", esito["riepilogo"].lower())

    def test_file_non_pdf_finisce_in_errore_senza_esplodere(self):
        from .services.referti_intake import elabora_contenuto

        righe = elabora_contenuto(b"non sono un pdf", "finto.pdf")
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0].esito, RefertoIntakeRiga.ESITO_ERRORE)

    def test_stesso_file_non_viene_rielaborato(self):
        from .services.referti_intake import _gia_visto, _impronta

        contenuto = b"%PDF-finto"
        sha = _impronta(contenuto)
        self.assertFalse(_gia_visto(sha, 1))
        RefertoIntakeRiga.objects.create(nome_file="x.pdf", sha256=sha, pagina=1)
        self.assertTrue(_gia_visto(sha, 1))

    def test_impronte_diverse_per_contenuti_diversi(self):
        from .services.referti_intake import _impronta

        self.assertNotEqual(_impronta(b"a"), _impronta(b"b"))


class OcrDisponibilitaTests(TestCase):
    """Tesseract assente non deve rompere niente."""

    def test_senza_tesseract_la_lettura_dichiara_il_motivo(self):
        from .services.referti_ocr import ErroreLettura

        with patch("anagrafica.services.referti_ocr.percorso_tesseract", return_value=""):
            from .services.referti_ocr import disponibile

            self.assertFalse(disponibile())

    def test_conta_pagine_su_file_non_pdf_ritorna_zero(self):
        from .services.referti_ocr import conta_pagine

        self.assertEqual(conta_pagine(b"non un pdf"), 0)
