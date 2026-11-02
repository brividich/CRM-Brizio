from datetime import date, datetime, time
from io import BytesIO
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import load_workbook

from core.models import SiteConfig

from . import mail_mensile, services, tasks
from .models import LetturaMensileContatori, Macchina

NOV = date(2026, 11, 1)
OTT = date(2026, 10, 1)


def _quando(giorno, ora=0, minuto=5):
    return timezone.make_aware(datetime.combine(date(2026, 11, giorno), time(ora, minuto)))


@override_settings(SITE_URL="https://hub.example.local",
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MailLettureMensiliTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a = Macchina.objects.create(reparto="Ufficio", matricola="SYN-A", host="192.0.2.41")
        self.b = Macchina.objects.create(reparto="Magazzino", matricola="SYN-B", host="192.0.2.42",
                                         snmp_ultimo_errore="[SNMP-003] nessuna risposta (sintetico)")
        Macchina.objects.create(reparto="Spenta", matricola="SYN-OFF", host="192.0.2.43", attiva=False)
        Macchina.objects.create(reparto="Senza IP", matricola="SYN-NOIP")
        SiteConfig.set(mail_mensile.CHIAVE_DESTINATARI, "contatori@example.com; ufficio@example.com")

    def _lettura(self, macchina, mese, base, giorno=1):
        return LetturaMensileContatori.objects.create(
            macchina=macchina, mese=mese, rilevata_il=_quando(giorno) if mese == NOV else
            timezone.make_aware(datetime.combine(mese, time(0, 5))),
            a4_bn=base, a3_bn=base // 10, a4_col=base // 2, a3_col=base // 20)

    def test_niente_mail_finche_manca_una_mfc(self):
        self._lettura(self.a, NOV, 1000)
        self.assertEqual(mail_mensile.notifica(NOV), "")
        self.assertEqual(len(mail.outbox), 0)

    def test_mail_completa_una_volta_con_copie_excel_e_link(self):
        self._lettura(self.a, OTT, 1000)
        self._lettura(self.a, NOV, 1200)
        self._lettura(self.b, NOV, 500)
        self.assertEqual(mail_mensile.notifica(NOV), mail_mensile.COMPLETA)
        self.assertEqual(mail_mensile.notifica(NOV), "")
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["contatori@example.com", "ufficio@example.com"])
        self.assertEqual(msg.subject, "Letture MFC 11/2026: tutte le 2 MFC lette")
        html = msg.alternatives[0][0]
        # Ufficio: 1200+120+600+60 contro 1000+100+500+50 = 330 copie nel mese.
        self.assertIn("330", html)
        self.assertIn("/contatori/letture/gestisci/?tipo=mensili", html)
        nome, contenuto, _ = msg.attachments[0]
        self.assertEqual(nome, "letture_mfc_2026-11.xlsx")
        ws = load_workbook(BytesIO(contenuto)).active
        righe = {r[0]: r for r in ws.iter_rows(min_row=2, values_only=True) if r[0]}
        self.assertEqual(righe["Ufficio"][-1], 330)
        self.assertIsNone(righe["Magazzino"][-1])  # nessuna lettura di ottobre

    def test_parziale_al_giro_finale_con_motivo_poi_completa(self):
        self._lettura(self.a, NOV, 1000)
        self.assertEqual(mail_mensile.notifica(NOV, ultimo_giro=True), mail_mensile.PARZIALE)
        self.assertEqual(mail_mensile.notifica(NOV, ultimo_giro=True), "")
        msg = mail.outbox[0]
        self.assertEqual(msg.subject, "Letture MFC 11/2026: 1 di 2, 1 mancanti")
        self.assertIn("nessuna risposta (sintetico)", msg.body)
        self._lettura(self.b, NOV, 500, giorno=8)
        self.assertEqual(mail_mensile.notifica(NOV), mail_mensile.COMPLETA)
        self.assertEqual(len(mail.outbox), 2)

    def test_senza_destinatari_nessun_invio_e_nessun_ripiego(self):
        SiteConfig.set(mail_mensile.CHIAVE_DESTINATARI, "")
        self._lettura(self.a, NOV, 1000)
        self._lettura(self.b, NOV, 500)
        with override_settings(ADMINS=[("Admin", "admin@example.com")]):
            self.assertEqual(mail_mensile.notifica(NOV), "")
        self.assertEqual(len(mail.outbox), 0)
        # Configurati dopo: la mail parte al giro successivo.
        SiteConfig.set(mail_mensile.CHIAVE_DESTINATARI, "contatori@example.com")
        self.assertEqual(mail_mensile.notifica(NOV), mail_mensile.COMPLETA)

    def test_ultimo_giro(self):
        self.assertFalse(mail_mensile.e_ultimo_giro(_quando(7, 22, 45)))
        self.assertTrue(mail_mensile.e_ultimo_giro(_quando(7, 23, 0)))
        self.assertTrue(mail_mensile.e_ultimo_giro(_quando(9, 10, 0)))
        self.assertFalse(mail_mensile.e_ultimo_giro(_quando(1, 0, 0)))

    def test_lettura_che_completa_il_mese_manda_la_mail(self):
        self._lettura(self.a, NOV, 1000)
        valori = {"a4_bn": 600, "a3_bn": 60, "a4_col": 300, "a3_col": 30}
        with mock.patch("django.utils.timezone.now", return_value=_quando(2, 9)), \
                mock.patch("contatori.services.interroga_macchina", return_value=valori):
            esito = tasks.leggi_mensile(self.b.pk, NOV.isoformat())
        self.assertTrue(esito["creata"])
        self.assertEqual(esito["mail"], mail_mensile.COMPLETA)
        self.assertEqual(len(mail.outbox), 1)

    def test_errore_di_invio_non_fa_fallire_la_lettura(self):
        self._lettura(self.a, NOV, 1000)
        self._lettura(self.b, NOV, 500)
        with mock.patch("core.email_utils.send_hub_mail", side_effect=RuntimeError("smtp giù")):
            self.assertEqual(tasks._notifica_mensile(NOV), "errore")
        self.assertEqual(mail_mensile._stato_inviato(NOV), "")

    def test_copie_mensili_fonte_unica(self):
        ott, nov = self._lettura(self.a, OTT, 1000), self._lettura(self.a, NOV, 1200)
        self.assertEqual(services.copie_mensili(nov, ott)["totale"], 330)
        self.assertEqual(services.copie_mensili(nov, ott)["a4_bn"], 200)
        self.assertIsNone(services.copie_mensili(ott, nov))  # contatori scesi
        self.assertEqual(services.righe_mensili_macchina(self.a)[0]["copie"], 330)
