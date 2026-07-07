"""MOD.128 MPQ — F5 integrazione timbri.

Il timbro fisico (``timbri.RegistroTimbro``) può essere collegato a
un'abilitazione persona×processo (MOD.128). Quando l'abilitazione **non è più
operativa** (revocata/sospesa/dismessa, oppure processo scaduto) il timbro
collegato viene **sospeso automaticamente** (§10.3: con data di sospensione);
al ritorno operativo l'auto-sospensione viene revocata. Regola idempotente,
speculare a ``skillmatrix_continuita`` (MARKER per distinguere le sospensioni
automatiche da quelle manuali). Le notifiche MSM riusano l'infrastruttura email
esistente (``send_hub_mail`` + ``get_reminder_recipients``).

Nessun dato reale: esempi fittizi.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import AbilitazioneProcesso, ClienteQualificante, ProcessoQualificato


def _make_ab(stato=AbilitazioneProcesso.STATO_ATTIVA, scadenza=None):
    cli = ClienteQualificante.objects.create(nome=f"Cliente {timezone.now().microsecond}")
    kwargs = dict(nome="Processo X", cliente=cli)
    if scadenza is not None:
        kwargs.update(tipo_validita=ProcessoQualificato.VALIDITA_DATA, data_scadenza=scadenza)
    proc = ProcessoQualificato.objects.create(**kwargs)
    return AbilitazioneProcesso.objects.create(
        legacy_anagrafica_id=7, processo=proc, stato=stato,
    )


def _make_timbro(ab=None, **extra):
    from timbri.models import OperatoreTimbri, RegistroTimbro
    op = OperatoreTimbri.objects.create(nome="Mario", cognome="Rossi")
    return RegistroTimbro.objects.create(
        operatore=op, codice_timbro="T-001", abilitazione_processo=ab, **extra
    )


class RegistroTimbroSospensioneModelTests(TestCase):
    def test_stato_label_sospeso(self):
        from timbri.models import RegistroTimbro
        t = _make_timbro()
        t.is_sospeso = True
        t.save()
        self.assertEqual(t.stato_label, "Sospeso")

    def test_sospeso_forza_non_attivo(self):
        t = _make_timbro()
        t.is_sospeso = True
        t.save()
        t.refresh_from_db()
        self.assertFalse(t.is_attivo)

    def test_fk_abilitazione_processo(self):
        ab = _make_ab()
        t = _make_timbro(ab=ab)
        self.assertEqual(t.abilitazione_processo, ab)
        self.assertIn(t, ab.timbri.all())


class MpqTimbriPropagazioneTests(TestCase):
    def test_sospende_su_abilitazione_revocata(self):
        from anagrafica.services.mpq_timbri import propaga_sospensioni
        ab = _make_ab(stato=AbilitazioneProcesso.STATO_REVOCATA)
        t = _make_timbro(ab=ab)
        stats = propaga_sospensioni()
        t.refresh_from_db()
        self.assertTrue(t.is_sospeso)
        self.assertIsNotNone(t.sospeso_dal)
        self.assertEqual(stats["sospesi"], 1)

    def test_sospende_su_processo_scaduto(self):
        from anagrafica.services.mpq_timbri import propaga_sospensioni
        ieri = timezone.localdate() - timedelta(days=1)
        ab = _make_ab(scadenza=ieri)  # processo scaduto, abilitazione ATTIVA
        t = _make_timbro(ab=ab)
        propaga_sospensioni()
        t.refresh_from_db()
        self.assertTrue(t.is_sospeso)

    def test_non_sospende_se_operativa(self):
        from anagrafica.services.mpq_timbri import propaga_sospensioni
        futuro = timezone.localdate() + timedelta(days=365)
        ab = _make_ab(scadenza=futuro)
        t = _make_timbro(ab=ab)
        stats = propaga_sospensioni()
        t.refresh_from_db()
        self.assertFalse(t.is_sospeso)
        self.assertEqual(stats["sospesi"], 0)

    def test_riattiva_al_ritorno_operativo(self):
        from anagrafica.services.mpq_timbri import propaga_sospensioni
        ab = _make_ab(stato=AbilitazioneProcesso.STATO_REVOCATA)
        t = _make_timbro(ab=ab)
        propaga_sospensioni()  # sospende
        ab.stato = AbilitazioneProcesso.STATO_ATTIVA
        ab.save()
        stats = propaga_sospensioni()  # riattiva
        t.refresh_from_db()
        self.assertFalse(t.is_sospeso)
        self.assertTrue(t.is_attivo)
        self.assertEqual(stats["riattivati"], 1)

    def test_non_riattiva_sospensione_manuale(self):
        from anagrafica.services.mpq_timbri import propaga_sospensioni
        ab = _make_ab()  # operativa
        t = _make_timbro(ab=ab)
        t.is_sospeso = True
        t.sospeso_motivo = "Sospensione manuale MSM"
        t.sospeso_riferimento = "verbale interno"  # niente MARKER
        t.save()
        propaga_sospensioni()
        t.refresh_from_db()
        self.assertTrue(t.is_sospeso)  # non toccata

    def test_idempotente(self):
        from anagrafica.services.mpq_timbri import propaga_sospensioni
        ab = _make_ab(stato=AbilitazioneProcesso.STATO_REVOCATA)
        _make_timbro(ab=ab)
        propaga_sospensioni()
        stats2 = propaga_sospensioni()
        self.assertEqual(stats2["sospesi"], 0)

    def test_ignora_timbri_senza_abilitazione(self):
        from anagrafica.services.mpq_timbri import propaga_sospensioni
        t = _make_timbro(ab=None)
        stats = propaga_sospensioni()
        t.refresh_from_db()
        self.assertFalse(t.is_sospeso)
        self.assertEqual(stats["sospesi"], 0)

    def test_ignora_timbri_archiviati(self):
        from anagrafica.services.mpq_timbri import propaga_sospensioni
        ab = _make_ab(stato=AbilitazioneProcesso.STATO_REVOCATA)
        t = _make_timbro(ab=ab, is_archived=True, is_attivo=False)
        propaga_sospensioni()
        t.refresh_from_db()
        self.assertFalse(t.is_sospeso)

    def test_dry_run_non_scrive(self):
        from anagrafica.services.mpq_timbri import propaga_sospensioni
        ab = _make_ab(stato=AbilitazioneProcesso.STATO_REVOCATA)
        t = _make_timbro(ab=ab)
        stats = propaga_sospensioni(apply=False)
        t.refresh_from_db()
        self.assertFalse(t.is_sospeso)
        self.assertEqual(stats["sospesi"], 1)  # conteggia il piano


@override_settings(ADMINS=[], DEFAULT_FROM_EMAIL="hub@example.com")
class MpqTimbriNotificaMsmTests(TestCase):
    def test_notifica_no_destinatari_non_crasha(self):
        from anagrafica.services.mpq_timbri import notifica_msm_sospensioni
        ab = _make_ab(stato=AbilitazioneProcesso.STATO_REVOCATA)
        t = _make_timbro(ab=ab)
        # nessun destinatario configurato → ritorna 0 senza inviare
        inviate = notifica_msm_sospensioni([t.pk])
        self.assertEqual(inviate, 0)

    def test_notifica_invia_a_destinatari(self):
        from django.core import mail
        from anagrafica.services.mpq_timbri import notifica_msm_sospensioni
        ab = _make_ab(stato=AbilitazioneProcesso.STATO_REVOCATA)
        t = _make_timbro(ab=ab)
        inviate = notifica_msm_sospensioni([t.pk], override=["msm@example.com"])
        self.assertEqual(inviate, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("msm@example.com", mail.outbox[0].to)
