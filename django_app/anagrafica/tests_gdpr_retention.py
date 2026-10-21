"""GDPR 21/10/2026: conservazione dei dati dei cessati e dei candidati «in database». Dati sintetici."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import (
    DipendenteAnagraficaAziendale,
    DipendenteAnagraficaCivile,
    FiglioACarico,
    ImportazioneCedolini,
    SaldoCedolino,
    TipoVisitaMedica,
    VisitaMedica,
)
from anagrafica.tests import _ensure_anagrafica_table

User = get_user_model()


def _admin(username):
    from core.models import UserOnboarding

    user = User.objects.create_superuser(username, f"{username}@example.invalid", "x")
    UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True, "completed_at": timezone.now()})
    return user


class CessatiRetentionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_anagrafica_table()
        super().setUpClass()

    def _persona(self, lid, cessazione, assunzione=None):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=lid, data_cessazione=cessazione, data_assunzione_ultima=assunzione,
            taglia_scarpe="42", telefono_aziendale="0000",
        )
        civile = DipendenteAnagraficaCivile.objects.create(
            legacy_anagrafica_id=lid, codice_fiscale=f"CFPROVA{lid}", iban="IT00X0000000000000000000000",
            email_privata="privata@example.invalid", indirizzo_residenza="Via Prova 1", genere="M",
            categoria_protetta=True,
        )
        FiglioACarico.objects.create(anagrafica=civile, nome="Figlio Prova", data_nascita=date(2000, 1, 1))
        imp = ImportazioneCedolini.objects.create(data_competenza=date(2010, 1, 31))
        SaldoCedolino.objects.create(importazione=imp, tax_code=f"CFPROVA{lid}", legacy_anagrafica_id=lid,
                                     data_competenza=date(2010, 1, 31), ferie_residui=Decimal("1"))
        tipo, _ = TipoVisitaMedica.objects.get_or_create(nome="Periodica GDPR", defaults={"durata_mesi": 12})
        VisitaMedica.objects.create(legacy_anagrafica_id=lid, tipo=tipo, data_svolgimento=date(2010, 1, 1),
                                    esito="IDONEO", prescrizioni="PRESCRIZIONE-SINTETICA", note="nota")

    def setUp(self):
        oggi = timezone.localdate()
        self._persona(101, oggi - timedelta(days=365 * 11))            # oltre i 10 anni
        self._persona(102, oggi - timedelta(days=365 * 3))             # cessato da poco
        self._persona(103, oggi - timedelta(days=365 * 11), assunzione=oggi - timedelta(days=100))  # riassunto

    def test_solo_i_cessati_oltre_il_termine_e_non_riassunti(self):
        from anagrafica.services.retention import cessati_da_minimizzare

        righe = {r["legacy_anagrafica_id"]: r for r in cessati_da_minimizzare()}
        self.assertEqual(set(righe), {101})
        self.assertEqual((righe[101]["civili"], righe[101]["figli"], righe[101]["saldi"], righe[101]["visite"]),
                         (1, 1, 1, 1))

    def test_ripulisci_toglie_i_dati_e_tiene_lo_storico(self):
        from anagrafica.services.retention import cessati_da_minimizzare
        from core.models import AuditLog

        self.client.force_login(_admin("gdpr_admin"))
        self.assertContains(self.client.get(reverse("anagrafica:retention")), "Dipendenti cessati da oltre 10 anni")
        self.client.post(reverse("anagrafica:retention"),
                         {"azione": "cessati", "ids": [101, 102, 103], "conferma": "ELIMINA"})
        civile = DipendenteAnagraficaCivile.objects.get(legacy_anagrafica_id=101)
        self.assertEqual((civile.codice_fiscale, civile.iban, civile.email_privata, civile.indirizzo_residenza),
                         ("", "", "", ""))
        self.assertFalse(civile.categoria_protetta)
        self.assertEqual(civile.genere, "M")
        self.assertFalse(FiglioACarico.objects.filter(anagrafica=civile).exists())
        self.assertFalse(SaldoCedolino.objects.filter(legacy_anagrafica_id=101).exists())
        visita = VisitaMedica.objects.get(legacy_anagrafica_id=101)
        self.assertEqual((visita.esito, visita.prescrizioni, visita.note), ("IDONEO", "", ""))
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=101)
        self.assertEqual((az.taglia_scarpe, az.telefono_aziendale), ("", ""))
        self.assertIsNotNone(az.data_cessazione)
        # gli altri due non si toccano
        self.assertEqual(DipendenteAnagraficaCivile.objects.get(legacy_anagrafica_id=102).codice_fiscale, "CFPROVA102")
        self.assertEqual(DipendenteAnagraficaCivile.objects.get(legacy_anagrafica_id=103).codice_fiscale, "CFPROVA103")
        self.assertEqual(cessati_da_minimizzare(), [])
        voce = AuditLog.objects.get(dettaglio__oggetto="retention_cessato")
        self.assertNotIn("CFPROVA101", str(voce.dettaglio))


class CandidatiInDatabaseTests(TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_anagrafica_table()
        super().setUpClass()

    def test_in_database_oltre_24_mesi_da_rivalutare_assunti_mai(self):
        from anagrafica.models_recruiting import Candidato
        from anagrafica.services.retention import candidati_scaduti

        pool = Candidato.objects.create(cognome="Pool", nome="Ada", stato=Candidato.STATO_IN_DATABASE)
        assunto = Candidato.objects.create(cognome="Assunto", nome="Ugo", stato=Candidato.STATO_ASSUNTO)
        recente = Candidato.objects.create(cognome="Recente", nome="Eva", stato=Candidato.STATO_IN_DATABASE)
        Candidato.objects.filter(pk__in=[pool.pk, assunto.pk]).update(updated_at=timezone.now() - timedelta(days=800))
        self.assertEqual(set(candidati_scaduti().values_list("pk", flat=True)), {pool.pk})
        self.assertNotIn(recente.pk, set(candidati_scaduti().values_list("pk", flat=True)))


class CandidatiChiusiDiRecenteTests(TestCase):
    """Fix 21/10/2026: un candidato chiuso un mese fa non e' «oltre i 24 mesi»."""

    @classmethod
    def setUpClass(cls):
        _ensure_anagrafica_table()
        super().setUpClass()

    def test_chiuso_da_un_mese_non_scaduto(self):
        from anagrafica.models_recruiting import Candidato
        from anagrafica.services.retention import _mesi_fa, candidati_scaduti

        cand = Candidato.objects.create(cognome="Mese", nome="Ida", stato=Candidato.STATO_SCARTATO)
        Candidato.objects.filter(pk=cand.pk).update(updated_at=timezone.now() - timedelta(days=30))
        self.assertFalse(candidati_scaduti().filter(pk=cand.pk).exists())
        self.assertEqual(_mesi_fa(date(2026, 3, 31), 1), date(2026, 2, 28))
        self.assertEqual(_mesi_fa(date(2026, 1, 15), 24), date(2024, 1, 15))
