"""Conferma della certificazione presenza inserita dalla pagina dedicata."""
from datetime import date, time
from unittest import mock

from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings

from assenze import mail_certificazione_presenza as svc
from assenze.models import CertificazionePresenza


def _cert(**kw):
    valori = dict(pk=7, nome_dipendente="ROSSI MARIO", data=date(2026, 11, 9),
                  entrata_mattina=time(6, 0), uscita_mattina=time(6, 0), turno_pomeriggio=True,
                  entrata_pomeriggio=time(14, 0), uscita_pomeriggio=time(22, 0), note="")
    valori.update(kw)
    return CertificazionePresenza(**valori)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
@mock.patch("automazioni.mail_inviate.registra")
@mock.patch.object(svc, "_assenze_mailbox", return_value="assenza@example.com")
class CertificazioneConfermataTests(TestCase):  # le mail passano dal flusso gestito (DB)
    def test_dipendente_e_chi_inserisce_con_ufficio_in_copia(self, _mb, registra):
        with mock.patch.object(svc, "email_dipendente_per_nome", return_value="mario.rossi@example.com"):
            self.assertTrue(svc.send_certificazione_confermata(
                _cert(), inserito_da_email="capo@example.com", inserito_da_nome="CAPO"))
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["mario.rossi@example.com", "capo@example.com"])
        self.assertEqual(msg.cc, ["assenza@example.com"])
        self.assertIn("14:00 - 22:00", msg.body)
        self.assertIn("8 h", msg.body)
        registra.assert_called_once()

    def test_senza_indirizzi_personali_va_almeno_all_ufficio(self, _mb, _registra):
        with mock.patch.object(svc, "email_dipendente_per_nome", return_value=""):
            self.assertTrue(svc.send_certificazione_confermata(_cert(), inserito_da_email=""))
        self.assertEqual(mail.outbox[0].to, ["assenza@example.com"])
        self.assertEqual(mail.outbox[0].cc, [])


class EmailDipendentePerNomeTests(SimpleTestCase):
    def _righe(self, righe):
        from assenze.views import _helpers
        return [
            mock.patch.object(_helpers, "_table_exists", return_value=True),
            mock.patch.object(_helpers, "legacy_table_columns", return_value={"nome", "cognome", "email", "email_notifica", "attivo"}),
            mock.patch.object(_helpers, "_fetch_all_dict", return_value=righe),
        ]

    def _con(self, righe, nominativo):
        patches = self._righe(righe)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return svc.email_dipendente_per_nome(nominativo)

    def test_un_solo_omonimo_restituisce_l_indirizzo(self):
        righe = [{"nome": "Mario", "cognome": "Rossi", "email": "mrossi", "email_notifica": "m.rossi@example.com"}]
        self.assertEqual(self._con(righe, "ROSSI MARIO"), "m.rossi@example.com")

    def test_omonimi_con_indirizzi_diversi_niente_mail(self):
        righe = [{"nome": "Mario", "cognome": "Rossi", "email": "", "email_notifica": "a@example.com"},
                 {"nome": "Mario", "cognome": "Rossi", "email": "", "email_notifica": "b@example.com"}]
        self.assertEqual(self._con(righe, "ROSSI MARIO"), "")
