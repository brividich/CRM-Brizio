"""Registro delle sostituzioni di toner e consumabili, da MFC e Monitor. Dati sintetici."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from . import services
from .models import DispositivoSNMP, LetturaConsumabile, Macchina, RilevazioneSNMP, SostituzioneConsumabile, StatoSNMP
from .snmp import SYS_DESCR, SYS_NAME, SYS_OBJECT_ID
from .stampanti import registra_sostituzioni, registro_sostituzioni


def _toner(pct, nome="Toner Nero", indice="1.1"):
    return [{"indice": indice, "nome": nome, "pct": pct, "tipo": "toner"}]


class RilevaSostituzioneTest(TestCase):
    def setUp(self):
        self.device = DispositivoSNMP.objects.create(nome="Stampante sintetica", host="192.0.2.90",
                                                     categoria=DispositivoSNMP.Categoria.STAMPANTE)

    def test_livello_risalito_registra_il_cambio(self):
        prima_il = timezone.now() - timedelta(hours=1)
        self.assertEqual(registra_sostituzioni(self.device, _toner(4), _toner(100), prima_il=prima_il), 1)
        s = SostituzioneConsumabile.objects.get()
        self.assertEqual((s.dispositivo, s.nome, s.tipo, s.pct_prima, s.pct_dopo), (self.device, "Toner Nero", "toner", 4, 100))
        self.assertEqual(s.ultima_lettura_prima, prima_il)

    def test_oscillazioni_e_livelli_mancanti_non_sono_cambi(self):
        self.assertEqual(registra_sostituzioni(self.device, _toner(40), _toner(45)), 0)  # +5: rumore di lettura
        self.assertEqual(registra_sostituzioni(self.device, _toner(40), _toner(30)), 0)
        self.assertEqual(registra_sostituzioni(self.device, _toner(None), _toner(100)), 0)
        self.assertEqual(registra_sostituzioni(self.device, None, _toner(100)), 0)
        self.assertEqual(registra_sostituzioni(self.device, _toner(10, nome="Ciano"), _toner(100)), 0)

    def test_stesso_cambio_visto_due_volte_si_registra_una_volta(self):
        adesso = timezone.now()
        registra_sostituzioni(self.device, _toner(5), _toner(100), adesso)
        registra_sostituzioni(self.device, _toner(5, indice=None), _toner(99, indice=None), adesso + timedelta(hours=12))
        self.assertEqual(SostituzioneConsumabile.objects.count(), 1)
        registra_sostituzioni(self.device, _toner(3), _toner(100), adesso + timedelta(days=40))
        self.assertEqual(SostituzioneConsumabile.objects.count(), 2)

    def test_registro_durata_e_conteggio_annuale(self):
        adesso = timezone.now()
        for giorni_fa in (100, 40):
            registra_sostituzioni(self.device, _toner(2), _toner(100), adesso - timedelta(days=giorni_fa))
        registra_sostituzioni(self.device, _toner(2, nome="Tamburo"), _toner(100, nome="Tamburo"), adesso - timedelta(days=10))
        out = registro_sostituzioni(self.device)
        recente, tamburo, primo = out["sostituzioni_registro"][1], out["sostituzioni_registro"][0], out["sostituzioni_registro"][2]
        self.assertEqual((tamburo.nome, tamburo.giorni_durata), ("Tamburo", None))
        self.assertEqual((recente.nome, recente.giorni_durata), ("Toner Nero", 60))
        self.assertIsNone(primo.giorni_durata)
        self.assertEqual(out["sostituzioni_anno"], [("Toner Nero", 2), ("Tamburo", 1)])


class SostituzioneMfcTest(TestCase):
    def setUp(self):
        self.m = Macchina.objects.create(reparto="Alfa", matricola="SYN-S1", host="192.0.2.91")

    def test_lettura_giornaliera_registra_il_cambio(self):
        ieri = timezone.now() - timedelta(days=1)
        services.salva_consumabili(self.m, [{"nome": "Nero", "pct": 3}, {"nome": "Ciano", "pct": 50}], ieri)
        services.salva_consumabili(self.m, [{"nome": "Nero", "pct": 100}, {"nome": "Ciano", "pct": 49}])
        s = SostituzioneConsumabile.objects.get()
        self.assertEqual((s.macchina, s.nome, s.pct_prima, s.pct_dopo, s.ultima_lettura_prima), (self.m, "Nero", 3, 100, ieri))
        self.assertEqual(LetturaConsumabile.objects.count(), 4)

    def test_scheda_mfc_mostra_il_registro(self):
        user = get_user_model().objects.create(username="sost_admin", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=user, completed=True)
        self.client.force_login(user)
        registra_sostituzioni(self.m, [{"nome": "Toner Magenta", "pct": 1}], [{"nome": "Toner Magenta", "pct": 100}])
        page = self.client.get(reverse("contatori:macchina", args=[self.m.pk]))
        self.assertContains(page, "Sostituzioni consumabili")
        self.assertContains(page, "Toner Magenta")
        self.assertContains(page, "1% → 100%")


class SostituzioneMonitorTest(TestCase):
    def test_interrogazione_confronta_con_la_lettura_precedente(self):
        device = DispositivoSNMP.objects.create(nome="Kyocera sintetica", host="192.0.2.92",
                                                categoria=DispositivoSNMP.Categoria.STAMPANTE)
        prima_il = timezone.now() - timedelta(minutes=5)
        RilevazioneSNMP.objects.create(dispositivo=device, stato=StatoSNMP.OK, rilevata_il=prima_il,
                                       dati_stampante={"contatori": [], "consumabili": _toner(2)})
        identita = {SYS_DESCR: "KYOCERA TASKalfa sintetica", SYS_NAME: "prt-syn", SYS_OBJECT_ID: "1.3.6.1.4.1.1347.43.5.1"}
        with mock.patch("contatori.snmp.leggi_oids", return_value=(identita, {})), \
             mock.patch("contatori.snmp.leggi_colonna", return_value=[100]), \
             mock.patch("contatori.printer_snmp.leggi_stampante",
                        return_value={"contatori": [{"indice": "1.1", "valore": 100, "unita": "impressioni"}],
                                      "consumabili": _toner(98), "errori": {}}):
            services.interroga_dispositivo(device)
        s = device.sostituzioni_consumabili.get()
        self.assertEqual((s.pct_prima, s.pct_dopo, s.ultima_lettura_prima), (2, 98, prima_il))
