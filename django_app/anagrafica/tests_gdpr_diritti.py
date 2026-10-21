"""GDPR 21/10/2026, checklist E2-E6: diritti dell'interessato e letture tracciate. Dati sintetici."""
import io
import json
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import (
    DipendenteAnagraficaCivile,
    ImportazioneCedolini,
    RichiestaRettifica,
    SaldoCedolino,
    TipoVisitaMedica,
    VisitaMedica,
)
from anagrafica.tests import _ensure_anagrafica_table
from core.legacy_models import AnagraficaDipendente
from core.models import AuditLog

User = get_user_model()
IO = "anagrafica.views._helpers._current_legacy_anagrafica_id"


def _utente(username, superuser=False):
    from core.models import UserOnboarding

    if superuser:
        user = User.objects.create_superuser(username, f"{username}@example.invalid", "x")
    else:
        user = User.objects.create_user(username, password="x")
    UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True, "completed_at": timezone.now()})
    return user


class MieiDatiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_anagrafica_table()
        super().setUpClass()

    def setUp(self):
        self.io = AnagraficaDipendente.objects.create(nome="Ivo", cognome="Sintetico", reparto="Officina")
        self.altro = AnagraficaDipendente.objects.create(nome="Ada", cognome="Altra", reparto="Officina")
        DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=self.io.id, iban="IT00X0000000000000000000001")
        imp = ImportazioneCedolini.objects.create(data_competenza=date(2026, 9, 30))
        SaldoCedolino.objects.create(importazione=imp, tax_code="X", legacy_anagrafica_id=self.io.id,
                                     data_competenza=date(2026, 9, 30), ferie_residui=Decimal("12.5"))
        SaldoCedolino.objects.create(importazione=imp, tax_code="Y", legacy_anagrafica_id=self.altro.id,
                                     data_competenza=date(2026, 9, 30), ferie_residui=Decimal("99.75"))
        tipo = TipoVisitaMedica.objects.create(nome="Periodica diritti", durata_mesi=12)
        VisitaMedica.objects.create(legacy_anagrafica_id=self.io.id, tipo=tipo,
                                    data_svolgimento=timezone.localdate() - timedelta(days=10),
                                    esito="IDONEO", prescrizioni="PRESCRIZIONE-RISERVATA")
        self.user = _utente("gdpr_io")
        self.client.force_login(self.user)

    def test_zip_solo_i_miei_dati_senza_prescrizioni_e_registrato(self):
        with mock.patch(IO, return_value=self.io.id):
            resp = self.client.get(reverse("anagrafica:miei_dati_zip"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/zip")
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        self.assertIn("LEGGIMI.txt", z.namelist())
        dati = json.loads(z.read("dati.json"))
        self.assertEqual(dati["anagrafica_civile"][0]["iban"], "IT00X0000000000000000000001")
        self.assertEqual(dati["saldi_ferie_permessi"][0]["ferie_residui"], "12.50")
        tutto = json.dumps(dati)
        self.assertNotIn("99.75", tutto)
        self.assertNotIn("PRESCRIZIONE-RISERVATA", tutto)
        self.assertEqual(dati["visite_mediche"][0]["giudizio"], "IDONEO")
        self.assertTrue(AuditLog.objects.filter(azione="DATI_PERSONALI_ESPORTATI").exists())

    def test_zip_senza_collegamento_404(self):
        with mock.patch(IO, return_value=None):
            self.assertEqual(self.client.get(reverse("anagrafica:miei_dati_zip")).status_code, 404)

    def test_segnalazione_e_risposta_hr(self):
        with mock.patch(IO, return_value=self.io.id):
            self.client.post(reverse("anagrafica:segnala_rettifica"),
                             {"ambito": "ANAGRAFICA", "testo": "Indirizzo di residenza vecchio"})
            pagina = self.client.get(reverse("anagrafica:mia_scheda"))
        richiesta = RichiestaRettifica.objects.get()
        self.assertEqual((richiesta.legacy_anagrafica_id, richiesta.stato), (self.io.id, RichiestaRettifica.STATO_APERTA))
        self.assertContains(pagina, "In lavorazione")
        # un utente qualunque non apre la pagina HR
        with mock.patch("anagrafica.views._helpers._check_hr_permission", return_value=False), \
             mock.patch("anagrafica.views._helpers._is_anagrafica_admin", return_value=False):
            self.assertEqual(self.client.get(reverse("anagrafica:rettifiche")).status_code, 403)
        self.client.force_login(_utente("gdpr_hr", superuser=True))
        self.assertContains(self.client.get(reverse("anagrafica:rettifiche")), "Indirizzo di residenza vecchio")
        self.client.post(reverse("anagrafica:rettifiche"), {"id": richiesta.pk, "risposta": "Corretto."})
        richiesta.refresh_from_db()
        self.assertEqual((richiesta.stato, richiesta.risposta), (RichiestaRettifica.STATO_CHIUSA, "Corretto."))
        self.assertTrue(AuditLog.objects.filter(azione="RETTIFICA_CHIUSA").exists())

    def test_segnalazione_vuota_rifiutata(self):
        with mock.patch(IO, return_value=self.io.id):
            self.client.post(reverse("anagrafica:segnala_rettifica"), {"ambito": "ALTRO", "testo": "x"})
        self.assertFalse(RichiestaRettifica.objects.exists())


class LettureTracciateTests(TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_anagrafica_table()
        super().setUpClass()

    def test_scheda_dipendente_una_riga_per_ora(self):
        dip = AnagraficaDipendente.objects.create(nome="Eva", cognome="Lettura")
        self.client.force_login(_utente("gdpr_lettore", superuser=True))
        url = reverse("anagrafica:dipendente_detail", args=[dip.id])
        self.client.get(url)
        self.client.get(url)
        self.assertEqual(AuditLog.objects.filter(azione="DIPENDENTE_SCHEDA_VISUALIZZATA",
                                                 oggetto_id=str(dip.id)).count(), 1)


class CampiCifratiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_anagrafica_table()
        super().setUpClass()

    def test_iban_e_prescrizioni_cifrati_nel_db_e_leggibili(self):
        from cryptography.fernet import Fernet
        from django.db import connection
        from django.test import override_settings

        with override_settings(DOCUMENT_ENCRYPTION_KEY=Fernet.generate_key().decode()):
            civ = DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=777, iban="IT00X0000000000000000000777")
            with connection.cursor() as c:
                c.execute("SELECT iban FROM anagrafica_dipendenteanagraficacivile WHERE id = %s", [civ.pk])
                grezzo = c.fetchone()[0]
            self.assertTrue(grezzo.startswith("enc1:"))
            self.assertNotIn("0777", grezzo)
            civ.refresh_from_db()
            self.assertEqual(civ.iban, "IT00X0000000000000000000777")
            # il vuoto resta vuoto: i filtri campo="" funzionano
            DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=778, iban="")
            self.assertTrue(DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=778, iban="").exists())

    def test_comando_cifra_i_valori_storici(self):
        from io import StringIO

        from cryptography.fernet import Fernet
        from django.core.management import call_command
        from django.db import connection
        from django.test import override_settings

        civ = DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=779, iban="IT00X0000000000000000000779")
        with override_settings(DOCUMENT_ENCRYPTION_KEY=Fernet.generate_key().decode()):
            call_command("cifra_campi_esistenti", "--apply", stdout=StringIO())
            with connection.cursor() as c:
                c.execute("SELECT iban FROM anagrafica_dipendenteanagraficacivile WHERE id = %s", [civ.pk])
                self.assertTrue(c.fetchone()[0].startswith("enc1:"))
            civ.refresh_from_db()
            self.assertEqual(civ.iban, "IT00X0000000000000000000779")
