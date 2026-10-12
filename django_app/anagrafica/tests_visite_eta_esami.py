"""Fasce d'età dei tipi di visita, «tipologia cambiata», storico rinnovato, referti di laboratorio.

Dati sintetici: nomi, date e id inventati.
"""
from datetime import date, timedelta
from importlib import import_module

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    DipendenteAnagraficaCivile,
    DipendenteRuoloOperativo,
    RuoloOperativo,
    TipoVisitaMedica,
    VisitaMedica,
)
from .models_sorveglianza import RefertoIntakeConfig, RefertoIntakeRiga, RequisitoVisitaDipendente
from .tests_visite_robustezza import _crea_dipendenti


def _anni_fa(oggi: date, anni: int, giorni: int = 0) -> date:
    try:
        base = oggi.replace(year=oggi.year - anni)
    except ValueError:
        base = oggi.replace(year=oggi.year - anni, day=28)
    return base - timedelta(days=giorni)


class _BaseVdt(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.quinq = TipoVisitaMedica.objects.create(
            nome="Oculistica VDT (Quinquennale) sint", durata_mesi=60,
            categoria="Oculistica VDT sint", eta_massima=49,
        )
        self.bien = TipoVisitaMedica.objects.create(
            nome="Oculistica VDT (Biennale) sint", durata_mesi=24,
            categoria="Oculistica VDT sint", eta_minima=50,
        )
        self.ruolo = RuoloOperativo.objects.create(nome="Videoterminalista sint")
        self.quinq.ruoli_operativi.add(self.ruolo)
        _crea_dipendenti(9301)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=9301, ruolo=self.ruolo)

    def _nascita(self, data):
        DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=9301, data_nascita=data)

    def _stato(self):
        from .services.visite import stato_visite

        return {r["tipo"].pk: r for r in stato_visite(9301)}


class FasceEtaTests(_BaseVdt):
    def test_tipo_e_fascia(self):
        self.assertTrue(self.quinq.vale_per_eta(49))
        self.assertFalse(self.quinq.vale_per_eta(50))
        self.assertTrue(self.bien.vale_per_eta(50))
        self.assertTrue(self.bien.vale_per_eta(None))
        self.assertEqual(self.bien.fascia_eta_label, "dai 50 anni")

    def test_sotto_i_50_resta_quinquennale(self):
        self._nascita(_anni_fa(self.oggi, 40))
        stato = self._stato()
        self.assertIn(self.quinq.pk, stato)
        self.assertNotIn(self.bien.pk, stato)

    def test_dai_50_diventa_biennale_con_motivo_e_scadenza_non_prima_del_compleanno(self):
        # 50 anni compiuti 30 giorni fa; ultima visita quinquennale di 3 anni fa.
        nascita = _anni_fa(self.oggi, 50, giorni=30)
        self._nascita(nascita)
        visita = VisitaMedica.objects.create(
            legacy_anagrafica_id=9301, tipo=self.quinq, data_svolgimento=_anni_fa(self.oggi, 3),
        )
        riga = self._stato()[self.bien.pk]
        self.assertEqual(riga["ultima"].pk, visita.pk)
        self.assertIn("Tipologia cambiata", riga["cambio"])
        self.assertIn("ha compiuto 50 anni", riga["cambio"])
        compleanno = nascita.replace(year=nascita.year + 50)
        self.assertEqual(riga["data_cambio"], compleanno)
        # Prudente pura darebbe visita + 24 mesi (un anno fa): mai prima del compleanno.
        self.assertEqual(riga["data_scadenza"], compleanno)

    def test_visita_dopo_i_50_scade_con_la_periodicita_nuova(self):
        self._nascita(_anni_fa(self.oggi, 52))
        fatta = self.oggi - timedelta(days=200)
        VisitaMedica.objects.create(legacy_anagrafica_id=9301, tipo=self.quinq, data_svolgimento=fatta)
        from .models import _add_months

        riga = self._stato()[self.bien.pk]
        self.assertEqual(riga["data_scadenza"], _add_months(fatta, 24))

    def test_il_protocollo_del_medico_non_si_sostituisce(self):
        self._nascita(_anni_fa(self.oggi, 55))
        DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=9301).delete()
        RequisitoVisitaDipendente.objects.create(
            legacy_anagrafica_id=9301, tipo=self.quinq, esame="Oculistica VDT",
            periodicita="quinquennale", data_certificato=self.oggi - timedelta(days=10), attivo=True,
        )
        stato = self._stato()
        self.assertIn(self.quinq.pk, stato)
        self.assertNotIn(self.bien.pk, stato)

    def test_ricalcolo_scrive_la_nota_sulla_visita(self):
        from .services.scadenze import ricalcola_visite

        self._nascita(_anni_fa(self.oggi, 51))
        visita = VisitaMedica.objects.create(
            legacy_anagrafica_id=9301, tipo=self.quinq, data_svolgimento=self.oggi - timedelta(days=100),
        )
        ricalcola_visite([9301])
        visita.refresh_from_db()
        self.assertTrue(visita.scadenza_nota.startswith("Tipologia cambiata"))


class SchedaDipendenteTests(_BaseVdt):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(
            username="ve_admin", email="ve_admin@example.test", password="x",
        )
        self.client.force_login(self.admin)

    def test_storico_rinnovata_senza_pallino_e_titolo_corretto(self):
        self._nascita(_anni_fa(self.oggi, 40))
        vecchia = VisitaMedica.objects.create(
            legacy_anagrafica_id=9301, tipo=self.quinq, data_svolgimento=_anni_fa(self.oggi, 6),
        )
        nuova = VisitaMedica.objects.create(
            legacy_anagrafica_id=9301, tipo=self.quinq, data_svolgimento=self.oggi - timedelta(days=30),
        )
        from .services.visite import visite_storico

        storico = {v.pk: v for v in visite_storico(9301)}
        self.assertEqual(storico[vecchia.pk].sostituita_da.pk, nuova.pk)
        self.assertIsNone(storico[nuova.pk].sostituita_da)

        pagina = self.client.get(reverse("anagrafica:dipendente_detail", args=[9301])).content.decode()
        self.assertNotIn("in base ai ruoli operativi", pagina)
        self.assertIn("rinnovata il", pagina)

    def test_stesso_giorno_stessa_famiglia_segnalato(self):
        self._nascita(_anni_fa(self.oggi, 51))
        giorno = self.oggi - timedelta(days=40)
        VisitaMedica.objects.create(legacy_anagrafica_id=9301, tipo=self.quinq, data_svolgimento=giorno)
        VisitaMedica.objects.create(legacy_anagrafica_id=9301, tipo=self.bien, data_svolgimento=giorno)
        from .services.visite import visite_storico

        self.assertTrue(all(v.stesso_giorno for v in visite_storico(9301)))


class ImpostazioniFasciaEtaTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="ve_imp", email="ve_imp@example.test", password="x",
        )
        self.client.force_login(self.admin)

    def test_crea_con_fascia_e_rifiuta_fascia_invertita(self):
        url = reverse("anagrafica:tipo_visita_medica_create")
        self.client.post(url, {"nome": "Fascia sint", "durata_mesi": "24", "eta_minima": "50"})
        self.assertEqual(TipoVisitaMedica.objects.get(nome="Fascia sint").eta_minima, 50)
        self.client.post(url, {"nome": "Invertita sint", "durata_mesi": "24", "eta_minima": "60", "eta_massima": "40"})
        self.assertFalse(TipoVisitaMedica.objects.filter(nome="Invertita sint").exists())


class MigrazioneOculisticaVdtTests(TestCase):
    def test_configura_solo_la_coppia_e_solo_i_campi_vuoti(self):
        modulo = import_module("anagrafica.migrations.0166_visite_fasce_eta_esami")
        q = TipoVisitaMedica.objects.create(nome="Visita Oculistica Terminalisti (Quinquennale)", durata_mesi=60)
        b = TipoVisitaMedica.objects.create(nome="Visita Oculistica Terminalisti (Biennale)", durata_mesi=24)
        altro = TipoVisitaMedica.objects.create(nome="Visita Oculistica (Annuale)", durata_mesi=12)
        modulo.configura_oculistica_vdt(django_apps, None)
        q.refresh_from_db(); b.refresh_from_db(); altro.refresh_from_db()
        self.assertEqual((q.eta_massima, b.eta_minima), (49, 50))
        self.assertEqual(q.categoria, b.categoria)
        self.assertTrue(q.categoria)
        self.assertEqual(altro.categoria, "")
        self.assertIsNone(altro.eta_minima)


_REFERTO_LAB = """LABORATORIO ANALISI CLINICHE SINTETICO
Paziente: VERDI GIUSEPPE
Data di nascita: 11/04/1975
Data prelievo: 03/02/2026        Data referto: 05/02/2026
ESAME EMOCROMOCITOMETRICO
Emoglobina      14.2   g/dL   Valori di riferimento 13.0 - 17.0
Glicemia        92     mg/dL  Valori di riferimento 70 - 110
"""


class ParserLaboratorioTests(TestCase):
    def test_riconosce_ed_estrae_paziente_e_prelievo(self):
        from .services.referti_parsing import TIPO_ESAMI, analizza_testo

        campi = analizza_testo(_REFERTO_LAB)
        self.assertEqual(campi.tipo_referto, TIPO_ESAMI)
        self.assertFalse(campi.e_certificato)
        self.assertEqual(campi.nominativo, "VERDI GIUSEPPE")
        self.assertEqual(campi.data_nascita, date(1975, 4, 11))
        self.assertEqual(campi.data_giudizio, date(2026, 2, 3))  # il prelievo, non il referto

    def test_un_testo_qualsiasi_non_e_un_referto_di_laboratorio(self):
        from .services.referti_parsing import analizza_testo

        self.assertEqual(analizza_testo("Fattura n. 12 del 03/02/2026 - Glicemia del mercato").tipo_referto, "")


class AcquisizioneLaboratorioTests(TestCase):
    def setUp(self):
        self.ematici = TipoVisitaMedica.objects.create(nome="Esami Ematici di Routine sint", durata_mesi=12)
        self.utente = get_user_model().objects.create_user("ve_revisore", password="x")
        self.config = RefertoIntakeConfig.load()

    def test_in_coda_mai_automatico_poi_registrato_come_eseguito(self):
        from .services.referti_intake import _elabora_testo
        from .services.referti_registrazione import registra, tipo_visita_per_riga
        from .tests_referti_intake import _anagrafica, _nascite

        tizio = {"legacy_id": 10, "nominativo": "VERDI GIUSEPPE", "cessato": False}
        with _anagrafica([tizio]), _nascite({10: date(1975, 4, 11)}):
            riga = _elabora_testo(_REFERTO_LAB, "lab.pdf", 0, config=self.config, origine="WEB")
        self.assertEqual(riga.tipo_referto, RefertoIntakeRiga.TIPO_ESAMI)
        self.assertEqual(riga.esito, RefertoIntakeRiga.ESITO_DA_RIVEDERE)
        self.assertEqual(riga.legacy_anagrafica_id_proposto, 10)
        self.assertFalse(VisitaMedica.objects.exists())
        self.assertEqual(tipo_visita_per_riga(riga).pk, self.ematici.pk)

        registra(riga, utente=self.utente)
        visita = VisitaMedica.objects.get(legacy_anagrafica_id=10)
        self.assertEqual(visita.tipo_id, self.ematici.pk)
        self.assertEqual(visita.data_svolgimento, date(2026, 2, 3))
        self.assertEqual(visita.esito, VisitaMedica.Esito.ESEGUITO)
