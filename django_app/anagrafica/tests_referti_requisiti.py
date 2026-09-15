"""Requisiti di visita dal protocollo del certificato e certificati oculistici (dati sintetici).

Il protocollo sanitario del certificato di idoneità elenca le visite a cui il
lavoratore è soggetto (decise dal medico competente), non visite svolte. Il
certificato oculistico ha data, nome ed esito scritti a mano: si completa in coda.
"""
from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import TipoVisitaMedica, VisitaMedica
from .models_sorveglianza import AliasEsitoIdoneita, RefertoIntakeRiga, RequisitoVisitaDipendente
from .services.referti_parsing import TIPO_OCULISTICA, analizza_testo
from .services.referti_registrazione import (
    ErroreRegistrazione,
    registra,
    tipo_oculistico_da_requisiti,
)
from .tests_referti_archivio_hr import OCULISTICO

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.medica = TipoVisitaMedica.objects.create(nome="Visita Medica", durata_mesi=12)
        self.ocul_biennale = TipoVisitaMedica.objects.create(
            nome="Visita Oculistica Terminalisti (Biennale)", durata_mesi=24,
        )
        self.antitetanica = TipoVisitaMedica.objects.create(nome="Vaccinazione Antitetanica", durata_mesi=120)
        from .models_sorveglianza import AliasEsameProtocollo

        AliasEsameProtocollo.objects.create(
            testo="Visita Oculistica", periodicita="biennale", tipo=self.ocul_biennale,
        )
        AliasEsitoIdoneita.objects.create(
            testo="IDONEO MANSIONE SPECIFICA", esito=VisitaMedica.Esito.IDONEO_MANSIONE,
        )
        self.utente = User.objects.create_user("revisore-req", password="x")

    def _certificato(self, data, protocollo=None, sha="a"):
        return RefertoIntakeRiga.objects.create(
            nome_file="idoneita.pdf", sha256=sha * 64,
            letto_nominativo="VERDI GIUSEPPE", letto_data_giudizio=data,
            letto_esito_testo="IDONEO MANSIONE SPECIFICA",
            letto_protocollo=protocollo or [
                {"esame": "Visita Medica", "periodicita": "annuale"},
                {"esame": "Visita Oculistica", "periodicita": "biennale"},
                {"esame": "Vaccinazione Antitetanica", "periodicita": "decennale"},
            ],
            legacy_anagrafica_id_proposto=10,
        )

    def _oculistico(self, **extra):
        campi = {
            "nome_file": "certificato-visita-oculistica-2024.pdf", "sha256": "o" * 64,
            "tipo_referto": RefertoIntakeRiga.TIPO_OCULISTICA,
            "legacy_anagrafica_id_proposto": 10,
        }
        campi.update(extra)
        return RefertoIntakeRiga.objects.create(**campi)


class RequisitiTests(_Base):
    def test_il_certificato_crea_una_visita_e_tre_requisiti(self):
        registra(self._certificato(date(2023, 5, 26)), utente=self.utente)
        self.assertEqual(list(VisitaMedica.objects.values_list("tipo__nome", flat=True)), ["Visita Medica"])
        self.assertEqual(
            set(RequisitoVisitaDipendente.objects.filter(attivo=True).values_list("tipo_id", flat=True)),
            {self.medica.id, self.ocul_biennale.id, self.antitetanica.id},
        )

    def test_il_certificato_piu_recente_sostituisce_i_requisiti(self):
        registra(self._certificato(date(2023, 5, 26)), utente=self.utente)
        registra(self._certificato(
            date(2024, 5, 20), sha="b",
            protocollo=[{"esame": "Visita Medica", "periodicita": "annuale"}],
        ), utente=self.utente)
        attivi = RequisitoVisitaDipendente.objects.filter(legacy_anagrafica_id=10, attivo=True)
        self.assertEqual(list(attivi.values_list("tipo_id", flat=True)), [self.medica.id])
        self.assertEqual(RequisitoVisitaDipendente.objects.filter(attivo=False).count(), 3)

    def test_un_certificato_piu_vecchio_resta_nello_storico(self):
        registra(self._certificato(date(2024, 5, 20), protocollo=[
            {"esame": "Visita Medica", "periodicita": "annuale"},
        ]), utente=self.utente)
        registra(self._certificato(date(2020, 1, 10), sha="c"), utente=self.utente)
        self.assertEqual(
            list(RequisitoVisitaDipendente.objects.filter(attivo=True).values_list("tipo_id", flat=True)),
            [self.medica.id],
        )
        self.assertEqual(VisitaMedica.objects.count(), 2)  # storico visite: entrambe le visite mediche

    def test_lo_scadenzario_vede_i_requisiti_come_visite_richieste(self):
        from .services.visite import STATO_MANCANTE, STATO_VALIDA, stato_visite

        registra(self._certificato(date.today().replace(day=1)), utente=self.utente)
        stati = {r["tipo"].id: r["stato"] for r in stato_visite(10)}
        self.assertEqual(stati[self.medica.id], STATO_VALIDA)
        self.assertEqual(stati[self.ocul_biennale.id], STATO_MANCANTE)
        self.assertEqual(stati[self.antitetanica.id], STATO_MANCANTE)

    def test_la_conformita_batch_include_i_requisiti(self):
        from .services.conformita import _visite_batch

        registra(self._certificato(date(2019, 1, 10)), utente=self.utente)
        esito = _visite_batch([10], include_dettaglio=True)
        self.assertIn(10, esito)
        self.assertTrue(any("Visita Medica" in d for d in esito[10]["dettagli"]))


class OculisticaTests(_Base):
    def test_il_modulo_dell_oculista_viene_riconosciuto(self):
        campi = analizza_testo(OCULISTICO)
        self.assertEqual(campi.tipo_referto, TIPO_OCULISTICA)
        self.assertFalse(campi.e_certificato)
        self.assertTrue(campi.e_referto)
        self.assertIsNone(campi.data_giudizio)  # scritta a mano: non si inventa

    def test_un_documento_qualsiasi_non_e_oculistico(self):
        self.assertEqual(analizza_testo("Richiesta ferie. Oculista in vacanza.").tipo_referto, "")

    def test_il_tipo_si_propone_dal_requisito_in_vigore_alla_data(self):
        registra(self._certificato(date(2023, 5, 26)), utente=self.utente)
        self.assertEqual(tipo_oculistico_da_requisiti(10, date(2023, 6, 1)), self.ocul_biennale)
        self.assertIsNone(tipo_oculistico_da_requisiti(99))

    def test_senza_data_non_si_registra(self):
        with self.assertRaises(ErroreRegistrazione):
            registra(self._oculistico(), utente=self.utente, esito_visita=VisitaMedica.Esito.IDONEO)

    def test_senza_esito_non_si_registra(self):
        registra(self._certificato(date(2023, 5, 26)), utente=self.utente)
        with self.assertRaises(ErroreRegistrazione):
            registra(self._oculistico(), utente=self.utente, data_visita=date(2023, 5, 10))

    def test_senza_requisito_ne_tipo_scelto_non_si_registra(self):
        with self.assertRaises(ErroreRegistrazione):
            registra(self._oculistico(), utente=self.utente,
                     data_visita=date(2023, 5, 10), esito_visita=VisitaMedica.Esito.IDONEO)

    def test_registrazione_con_data_esito_e_tipo_dal_requisito(self):
        registra(self._certificato(date(2023, 5, 26)), utente=self.utente)
        riga = self._oculistico()
        create = registra(riga, utente=self.utente, data_visita=date(2023, 5, 10),
                          esito_visita=VisitaMedica.Esito.IDONEO)
        self.assertEqual(len(create), 1)
        visita = create[0]
        self.assertEqual(visita.tipo, self.ocul_biennale)
        self.assertEqual(visita.data_svolgimento, date(2023, 5, 10))
        self.assertEqual(visita.data_scadenza, date(2025, 5, 10))
        riga.refresh_from_db()
        self.assertEqual(riga.esito, RefertoIntakeRiga.ESITO_OK)
        self.assertEqual(riga.letto_data_giudizio, date(2023, 5, 10))
        self.assertEqual(riga.tipo_visita_scelto, self.ocul_biennale)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CodaOculisticaTests(_Base):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("coda-ocul", "c@example.invalid", "x")
        self.client.force_login(self.admin)

    def test_la_coda_mostra_data_tipo_ed_esito_per_l_oculistico(self):
        riga = self._oculistico()
        contenuto = self.client.get("/anagrafica/visite-mediche/referti/").content.decode()
        self.assertIn(f'name="data_visita_{riga.pk}"', contenuto)
        self.assertIn(f'name="tipo_visita_{riga.pk}"', contenuto)
        self.assertIn(f'name="esito_visita_{riga.pk}"', contenuto)
        self.assertIn("Anno nel nome del file: 2024", contenuto)

    def test_conferma_dalla_coda_registra_la_visita_oculistica(self):
        riga = self._oculistico()
        self.client.post("/anagrafica/visite-mediche/referti/azioni/", {
            "azione": "conferma", "righe": [riga.pk],
            f"legacy_id_{riga.pk}": "10",
            f"data_visita_{riga.pk}": "2024-02-03",
            f"tipo_visita_{riga.pk}": str(self.ocul_biennale.pk),
            f"esito_visita_{riga.pk}": VisitaMedica.Esito.IDONEO,
        })
        visita = VisitaMedica.objects.get()
        self.assertEqual(visita.tipo, self.ocul_biennale)
        self.assertEqual(visita.data_svolgimento, date(2024, 2, 3))
        riga.refresh_from_db()
        self.assertEqual(riga.esito, RefertoIntakeRiga.ESITO_OK)

    def test_data_non_valida_lascia_il_referto_in_coda(self):
        riga = self._oculistico()
        self.client.post("/anagrafica/visite-mediche/referti/azioni/", {
            "azione": "conferma", "righe": [riga.pk],
            f"data_visita_{riga.pk}": "31-02-2024",
            f"esito_visita_{riga.pk}": VisitaMedica.Esito.IDONEO,
        })
        self.assertFalse(VisitaMedica.objects.exists())
        riga.refresh_from_db()
        self.assertEqual(riga.esito, RefertoIntakeRiga.ESITO_DA_RIVEDERE)
