"""Accessi di account amministratore su un PC, dal Registro log, nel riquadro Rischio. Dati sintetici."""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from assets.models import Asset
from registro_log.models import AccountAD, EventoRegistro
from security.models import SoftwareInstallation
from security.services import accessi_admin, rischio_asset as ra

OGGI = date(2026, 11, 8)


def _sw(host, hub, product="windows 11 pro", version="10.0.26200.1"):
    now = timezone.now()
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{product}|{version}", source_kind="watchguard", fonti=["watchguard"], host=host, host_display=host, hub_asset=hub,
        vendor="microsoft", vendor_raw="Microsoft", product=product, product_raw=product, version_raw=version, still_detected=True, seen_at=now, last_seen_at=now,
    )


def _accesso(host, account, giorni_fa=1, privilegiato=True, esito="ok", categoria="accesso"):
    return EventoRegistro.objects.create(quando=timezone.now() - timedelta(days=giorni_fa), categoria=categoria, host=host, account=account,
                                         esito=esito, privilegiato=privilegiato)


class AccessiAdminTests(TestCase):
    def setUp(self):
        self.pc = Asset.objects.create(asset_tag="PC-A1", name="PC-UFF-01", asset_type=Asset.TYPE_PC)
        self.srv = Asset.objects.create(asset_tag="SRV-A1", name="SRV-01", asset_type=Asset.TYPE_SERVER)
        _sw("pc-uff-01.dominio.local", self.pc)
        _sw("srv-01", self.srv)
        AccountAD.objects.create(sam="admin.it", gruppi_privilegiati=["Domain Admins"], password_non_scade=True)
        AccountAD.objects.create(sam="ex.admin", gruppi_privilegiati=["Administrators"], persona_cessata=True)

    def test_conta_solo_privilegiati_riusciti_su_quel_pc(self):
        _accesso("PC-UFF-01", "DOMINIO\\admin.it")
        _accesso("pc-uff-01.dominio.local", "admin.it@dominio.local", giorni_fa=3)
        _accesso("PC-UFF-01", "admin.it", esito="ko")
        _accesso("PC-UFF-01", "mrossi", privilegiato=False)
        _accesso("SRV-01", "admin.it")
        _accesso("PC-UFF-01", "admin.it", giorni_fa=45)
        dati = accessi_admin.per_asset(self.pc)
        self.assertEqual(dati["accessi"], 2)
        self.assertEqual([(a["sam"], a["accessi"], a["gruppi"], a["password_non_scade"]) for a in dati["account"]],
                         [("admin.it", 2, ["Domain Admins"], True)])

    def test_senza_registro_log_niente(self):
        self.assertIsNone(accessi_admin.per_asset(self.pc))

    def test_rischio_medio_su_pc_nota_su_server_alto_se_cessato(self):
        _accesso("PC-UFF-01", "admin.it")
        _accesso("SRV-01", "admin.it")
        v = ra.valuta(self.pc, OGGI)
        self.assertEqual(v["livello"], ra.MEDIO)
        self.assertTrue(any("account amministratore" in m for m in v["medi"]))
        self.assertTrue(any("password che non scade" in n for n in v["note"]))
        v = ra.valuta(self.srv, OGGI)
        self.assertFalse(any("account amministratore" in m for m in v["medi"]))  # su un server è normale: resta una nota
        self.assertTrue(any("account amministratore" in n for n in v["note"]))
        _accesso("PC-UFF-01", "ex.admin")
        v = ra.valuta(self.pc, OGGI)
        self.assertEqual(v["livello"], ra.ALTO)
        self.assertIn("persona cessata", v["alti"][0])


class RischioDotazioneHardwareTests(TestCase):
    def setUp(self):
        self.pc = Asset.objects.create(asset_tag="PC-A2", name="PC-UFF-02", asset_type=Asset.TYPE_PC, reparto="Ufficio",
                                       purchase_date=OGGI - timedelta(days=int(7 * 365.25)))
        _sw("pc-uff-02", self.pc)

    def test_dotazione_mancante_e_hardware_vecchio(self):
        from assets.models import SoftwareDotazioneAttesa

        SoftwareDotazioneAttesa.objects.create(programma="acme|acme antivirus", etichetta="Acme Antivirus", ambito="pc")
        v = ra.valuta(self.pc, OGGI)
        self.assertEqual(v["livello"], ra.MEDIO)
        self.assertIn("manca dalla dotazione attesa: Acme Antivirus", v["medi"])
        self.assertTrue(any(m.startswith("hardware da sostituire") for m in v["medi"]))
        self.assertEqual(v["hardware"]["giudizio"], "sostituire")
        self.assertEqual(v["dotazione"], ["Acme Antivirus"])
