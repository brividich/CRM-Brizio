from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from assets.models import Asset, AssetEndpoint
from contatori import services
from contatori.models import (
    ColonnaProfiloSNMP,
    DispositivoSNMP,
    Macchina,
    ProfiloSNMP,
    RilevazioneSNMP,
    SondaSNMP,
    StatoSNMP,
    ValoreSNMP,
)
from contatori.snmp import (
    PRT_SERIAL,
    SNMPError,
    SYS_DESCR,
    SYS_NAME,
    SYS_OBJECT_ID,
    SYS_UPTIME,
)


class OIDValidationTest(SimpleTestCase):
    def test_leggi_oids_rifiuta_oid_non_numerico_prima_del_network(self):
        from contatori.snmp import leggi_oids

        with self.assertRaisesMessage(SNMPError, "OID non valido"):
            leggi_oids("192.0.2.10", ["sysName.0"])

    def test_aggregazioni_walk(self):
        from contatori.snmp import aggrega_colonna

        self.assertEqual(aggrega_colonna([3, 9, 4], "MASSIMO"), 9)
        self.assertEqual(aggrega_colonna([3, 9, 4], "MINIMO"), 3)
        self.assertEqual(aggrega_colonna([3, 9, 4], "SOMMA"), 16)


class ProfiliSNMPTest(TestCase):
    def test_catalogo_iniziale_copre_stampanti_firewall_server_storage_e_ups(self):
        categorie = set(ProfiloSNMP.objects.values_list("categoria", flat=True))
        self.assertTrue({
            "STAMPANTE", "FIREWALL", "RETE", "SERVER", "STORAGE", "UPS",
        }.issubset(categorie))
        self.assertTrue(ProfiloSNMP.objects.filter(slug="kyocera").exists())
        self.assertTrue(ProfiloSNMP.objects.filter(slug="fortinet").exists())
        self.assertTrue(ProfiloSNMP.objects.filter(slug="dell-server").exists())

    def test_autodetect_kyocera_da_enterprise_oid_e_descrizione(self):
        profile = services.trova_profilo_snmp(
            sys_object_id="1.3.6.1.4.1.1347.43.5.1",
            sys_description="KYOCERA TASKalfa 3554ci",
        )
        self.assertIsNotNone(profile)
        self.assertEqual(profile.slug, "kyocera")

    def test_applica_profilo_materializza_sonde_e_override(self):
        device = DispositivoSNMP.objects.create(
            nome="Firewall", host="192.0.2.80",
        )
        profile = ProfiloSNMP.objects.get(slug="fortinet")
        created, updated = services.applica_profilo_dispositivo(device, profile)
        self.assertEqual(created, profile.colonne.count())
        self.assertEqual(updated, 0)
        device.refresh_from_db()
        self.assertEqual(device.profilo_snmp, profile)
        self.assertEqual(device.versione, "v2c")
        self.assertEqual(device.timeout, 5)
        self.assertTrue(device.sonde.filter(modalita="WALK").exists())
        self.assertFalse(device.sonde.filter(profilo_colonna__isnull=True).exists())

    def test_cambio_profilo_rimuove_solo_sonde_generate_dal_vecchio(self):
        device = DispositivoSNMP.objects.create(nome="Appliance", host="192.0.2.83")
        fortinet = ProfiloSNMP.objects.get(slug="fortinet")
        apc = ProfiloSNMP.objects.get(slug="apc-ups")
        services.applica_profilo_dispositivo(device, fortinet)
        manuale = SondaSNMP.objects.create(
            dispositivo=device, nome="Sonda manuale", oid="1.3.6.1.4.1.999.9.0",
        )

        services.applica_profilo_dispositivo(device, apc)

        self.assertTrue(device.sonde.filter(pk=manuale.pk).exists())
        self.assertFalse(device.sonde.filter(
            profilo_colonna__profilo=fortinet,
        ).exists())
        self.assertEqual(
            device.sonde.filter(profilo_colonna__profilo=apc).count(),
            apc.colonne.filter(attiva=True).count(),
        )

    @mock.patch("contatori.printer_snmp.leggi_stampante", return_value={
        "contatori": [{"indice": "1.1", "valore": 1234, "unita": "impressioni"}],
        "consumabili": [{"nome": "Black", "pct": 45, "nota": ""}], "errori": {},
    })
    @mock.patch("contatori.snmp.leggi_colonna", return_value=[1234])
    @mock.patch("contatori.snmp.leggi_oids")
    def test_prima_interrogazione_autoconfigura_kyocera(self, leggi, colonna, stampante):
        device = DispositivoSNMP.objects.create(
            nome="MFC magazzino", host="192.0.2.81",
            categoria=DispositivoSNMP.Categoria.STAMPANTE,
        )
        leggi.return_value = ({
            SYS_NAME: "kyocera-01",
            SYS_DESCR: "KYOCERA TASKalfa 3554ci",
            SYS_OBJECT_ID: "1.3.6.1.4.1.1347.43.5.1",
            SYS_UPTIME: 200,
            PRT_SERIAL: "KY-TEST-001",
        }, {})
        poll = services.interroga_dispositivo(device)
        device.refresh_from_db()
        self.assertEqual(device.profilo_snmp.slug, "kyocera")
        totale = poll.valori.get(sonda__oid="1.3.6.1.2.1.43.10.2.1.4")
        self.assertEqual(totale.valore_numero, 1234)
        self.assertEqual(poll.dati_stampante["consumabili"][0]["pct"], 45)
        self.assertEqual(device.matricola, "KY-TEST-001")
        self.assertTrue(device.sonde.filter(
            oid="1.3.6.1.2.1.43.10.2.1.4", modalita="WALK",
        ).exists())

    @mock.patch("contatori.snmp.leggi_specifiche")
    def test_mfc_con_profilo_personalizzato_legge_quattro_contatori(self, leggi):
        profile = ProfiloSNMP.objects.create(
            slug="mfc-test", nome="MFC test", produttore="Test",
            categoria=ProfiloSNMP.Categoria.STAMPANTE,
        )
        columns = []
        for order, key in enumerate(("a4_bn", "a3_bn", "a4_col", "a3_col"), 1):
            columns.append(ColonnaProfiloSNMP.objects.create(
                profilo=profile, nome=key, oid=f"1.3.6.1.4.1.999.1.{order}.0",
                contatore_mfc=key, ordine=order,
            ))
        leggi.return_value = ({c.oid: index * 100 for index, c in enumerate(columns, 1)}, {})
        machine = Macchina.objects.create(
            reparto="Test", matricola="MFC-PROFILE-1", modello="Kyocera test",
            host="192.0.2.82", profilo_snmp=profile,
        )
        values = services.interroga_macchina(machine)
        self.assertEqual(values, {
            "a4_bn": 100, "a3_bn": 200, "a4_col": 300, "a3_col": 400,
        })


class SoglieSondaTest(TestCase):
    def setUp(self):
        self.device = DispositivoSNMP.objects.create(
            nome="UPS laboratorio", host="192.0.2.10",
        )
        self.sonda = SondaSNMP.objects.create(
            dispositivo=self.device, nome="Temperatura",
            oid="1.3.6.1.4.1.999.1.0", unita="°C",
            soglia_warning_max=Decimal("30"),
            soglia_critica_max=Decimal("40"),
        )

    def test_soglie_ok_warning_critica(self):
        self.assertEqual(self.sonda.stato_per_valore(Decimal("25")), StatoSNMP.OK)
        self.assertEqual(self.sonda.stato_per_valore(Decimal("35")), StatoSNMP.WARNING)
        self.assertEqual(self.sonda.stato_per_valore(Decimal("45")), StatoSNMP.ERROR)

    def test_form_rifiuta_oid_duplicato_sullo_stesso_dispositivo(self):
        from contatori.forms import SondaSNMPForm

        form = SondaSNMPForm({
            "nome": "Duplicato", "oid": self.sonda.oid,
            "tipo_valore": self.sonda.tipo_valore, "fattore": "1", "ordine": "0",
        }, instance=SondaSNMP(dispositivo=self.device))
        self.assertFalse(form.is_valid())
        self.assertIn("oid", form.errors)

    def test_numeri_non_finiti_o_fuori_range_non_arrivano_al_database(self):
        for valore in ("NaN", "Infinity", "-Infinity", "1e25", "1e999999999"):
            with self.subTest(valore=valore):
                self.assertIsNone(services._numero_sonda(self.sonda, valore))


class PollingDispositivoTest(TestCase):
    def setUp(self):
        self.device = DispositivoSNMP.objects.create(
            nome="Lettore ingresso", categoria=DispositivoSNMP.Categoria.LETTORE,
            host="192.0.2.20",
        )
        self.sonda = SondaSNMP.objects.create(
            dispositivo=self.device, nome="Passaggi",
            oid="1.3.6.1.4.1.999.2.0", fattore=Decimal("2"),
            soglia_warning_max=Decimal("15"),
        )

    @mock.patch("contatori.snmp.leggi_oids")
    def test_poll_salva_identita_valore_convertito_e_salute(self, leggi):
        leggi.return_value = ({
            SYS_NAME: b"gate-01", SYS_DESCR: b"Reader X",
            SYS_OBJECT_ID: "1.3.6.1.4.1.999", SYS_UPTIME: 123400,
            self.sonda.oid: "5",
        }, {})

        poll = services.interroga_dispositivo(self.device)

        self.assertEqual(poll.stato, StatoSNMP.OK)
        self.assertEqual(poll.sys_uptime_seconds, 1234)
        valore = ValoreSNMP.objects.get(rilevazione=poll, sonda=self.sonda)
        self.assertEqual(valore.valore_numero, Decimal("10"))
        self.device.refresh_from_db()
        self.assertEqual(self.device.sys_name, "gate-01")
        self.assertEqual(self.device.snmp_stato, StatoSNMP.OK)

    @mock.patch("contatori.snmp.leggi_oids")
    def test_oid_sistema_opzionale_assente_non_genera_warning(self, leggi):
        leggi.return_value = (
            {SYS_NAME: "gate-01", self.sonda.oid: "2"},
            {SYS_DESCR: "noSuchInstance", SYS_OBJECT_ID: "noSuchInstance"},
        )
        poll = services.interroga_dispositivo(self.device)
        self.assertEqual(poll.stato, StatoSNMP.OK)

    @mock.patch("contatori.snmp.leggi_oids")
    def test_sonda_senza_risposta_genera_warning_e_valore_errore(self, leggi):
        leggi.return_value = ({SYS_NAME: "gate-01"}, {self.sonda.oid: "timeout"})
        poll = services.interroga_dispositivo(self.device)
        self.assertEqual(poll.stato, StatoSNMP.WARNING)
        valore = poll.valori.get()
        self.assertEqual(valore.stato, StatoSNMP.ERROR)
        self.assertEqual(valore.errore, "timeout")

    @mock.patch("contatori.snmp.leggi_oids", side_effect=SNMPError("irraggiungibile"))
    def test_errore_connessione_viene_storicizzato(self, _leggi):
        poll = services.interroga_dispositivo(self.device)
        self.assertEqual(poll.stato, StatoSNMP.ERROR)
        self.assertIn("irraggiungibile", poll.errore)
        self.device.refresh_from_db()
        self.assertEqual(self.device.snmp_stato, StatoSNMP.ERROR)
        self.assertEqual(ValoreSNMP.objects.count(), 0)


class SaluteMFCTest(TestCase):
    def setUp(self):
        self.mfc = Macchina.objects.create(
            reparto="Test", matricola="MFC-TEST-HEALTH",
            modello=Macchina.Modello.DX_C5840I, host="192.0.2.60",
        )

    @mock.patch("contatori.snmp.leggi_macchina", return_value={
        "a4_bn": 1, "a3_bn": 2, "a4_col": 3, "a3_col": 4,
    })
    def test_successo_aggiorna_salute(self, _leggi):
        services.interroga_macchina(self.mfc)
        self.mfc.refresh_from_db()
        self.assertEqual(self.mfc.snmp_stato, StatoSNMP.OK)
        self.assertIsNotNone(self.mfc.snmp_ultimo_controllo)
        self.assertEqual(self.mfc.snmp_ultimo_errore, "")

    @mock.patch("contatori.snmp.leggi_macchina", side_effect=SNMPError("timeout"))
    def test_errore_aggiorna_salute_e_viene_rilanciato(self, _leggi):
        with self.assertRaises(SNMPError):
            services.interroga_macchina(self.mfc)
        self.mfc.refresh_from_db()
        self.assertEqual(self.mfc.snmp_stato, StatoSNMP.ERROR)
        self.assertEqual(self.mfc.snmp_ultimo_errore, "[SNMP-003] timeout")  # codice di catalogo


class CentraleViewsAndAssetBridgeTest(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username="snmp_centrale_admin", password="test-only-password",
        )
        self.client.force_login(user)

    def test_centrale_e_form_sono_accessibili(self):
        response = self.client.get(reverse("contatori:snmp_centrale"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monitor SNMP")
        self.assertContains(response, "Multifunzione")
        self.assertEqual(
            self.client.get(reverse("contatori:snmp_dispositivo_nuovo")).status_code,
            200,
        )

    def test_catalogo_profili_renderizza_i_preset_principali(self):
        response = self.client.get(reverse("contatori:snmp_profili"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kyocera MFP e stampanti")
        self.assertContains(response, "FortiGate / Fortinet")
        self.assertContains(response, "Dell PowerEdge / iDRAC")

    def test_applica_profilo_da_portale_crea_le_sonde(self):
        profilo = ProfiloSNMP.objects.get(slug="fortinet")
        dispositivo = DispositivoSNMP.objects.create(
            nome="Firewall sede", host="192.0.2.29",
        )
        response = self.client.post(
            reverse(
                "contatori:snmp_dispositivo_applica_profilo",
                args=[dispositivo.pk],
            ),
            {"profilo": profilo.pk},
        )
        self.assertEqual(response.status_code, 302)
        dispositivo.refresh_from_db()
        self.assertEqual(dispositivo.profilo_snmp, profilo)
        self.assertEqual(dispositivo.categoria, DispositivoSNMP.Categoria.FIREWALL)
        self.assertEqual(
            dispositivo.sonde.count(), profilo.colonne.filter(attiva=True).count(),
        )

    def test_creazione_dispositivo_collega_asset_univoco_per_ip(self):
        asset = Asset.objects.create(asset_tag="IT-SNMP-01", name="Lettore badge")
        AssetEndpoint.objects.create(asset=asset, endpoint_name="LAN", ip="192.0.2.30")
        response = self.client.post(reverse("contatori:snmp_dispositivo_nuovo"), {
            "nome": "Lettore badge ingresso", "categoria": "LETTORE",
            "host": "192.0.2.30", "porta": "", "versione": "",
            "posizione": "Ingresso", "produttore": "", "modello": "",
            "matricola": "", "asset": "", "note": "", "attivo": "on",
        })
        self.assertEqual(response.status_code, 302)
        device = DispositivoSNMP.objects.get()
        self.assertEqual(device.asset_id, asset.pk)

        asset_page = self.client.get(reverse("assets:asset_view", args=[asset.pk]))
        self.assertContains(asset_page, "Monitoraggio MFC e SNMP")
        self.assertContains(asset_page, "Lettore badge ingresso")

    def test_collega_asset_command_include_dispositivi_generici(self):
        asset = Asset.objects.create(
            asset_tag="IT-SNMP-02", name="UPS", serial_number="UPS-SERIAL-1",
        )
        device = DispositivoSNMP.objects.create(
            nome="UPS CED", host="192.0.2.31", matricola="UPS-SERIAL-1",
        )
        output = StringIO()
        call_command("collega_asset", "--apply", stdout=output)
        device.refresh_from_db()
        self.assertEqual(device.asset_id, asset.pk)
        self.assertIn("SNMP", output.getvalue())

    def test_modifica_permette_scollegamento_asset_esplicito(self):
        asset = Asset.objects.create(asset_tag="IT-SNMP-03", name="Reader")
        AssetEndpoint.objects.create(asset=asset, endpoint_name="LAN", ip="192.0.2.32")
        device = DispositivoSNMP.objects.create(
            nome="Reader", host="192.0.2.32", asset=asset,
        )
        response = self.client.post(
            reverse("contatori:snmp_dispositivo_edit", args=[device.pk]),
            {"nome": device.nome, "host": device.host, "categoria": "LETTORE", "asset": ""},
        )
        self.assertEqual(response.status_code, 302)
        device.refresh_from_db()
        self.assertIsNone(device.asset_id)

    def test_dettaglio_mostra_ultimo_valore_per_sonda(self):
        device = DispositivoSNMP.objects.create(nome="Reader", host="192.0.2.33")
        sonda = SondaSNMP.objects.create(
            dispositivo=device, nome="Passaggi", oid="1.3.6.1.4.1.999.1.0",
        )
        for numero in (1, 2):
            poll = RilevazioneSNMP.objects.create(dispositivo=device, stato=StatoSNMP.OK)
            ValoreSNMP.objects.create(rilevazione=poll, sonda=sonda, valore_numero=numero)
        response = self.client.get(reverse("contatori:snmp_dispositivo", args=[device.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sonde"][0].ultimo_valore.valore_numero, 2)

    def test_poll_endpoint_e_solo_post(self):
        device = DispositivoSNMP.objects.create(nome="Switch", host="192.0.2.40")
        response = self.client.get(
            reverse("contatori:snmp_dispositivo_interroga", args=[device.pk]),
        )
        self.assertEqual(response.status_code, 405)

    @mock.patch("contatori.services.interroga_dispositivo")
    def test_poll_tutti_interroga_solo_dispositivi_attivi(self, poll):
        active = DispositivoSNMP.objects.create(nome="Attivo", host="192.0.2.50")
        DispositivoSNMP.objects.create(nome="Spento", host="192.0.2.51", attivo=False)
        poll.return_value = RilevazioneSNMP(
            dispositivo=active, stato=StatoSNMP.OK,
        )
        response = self.client.post(reverse("contatori:snmp_interroga_tutti"))
        self.assertEqual(response.status_code, 302)
        poll.assert_called_once_with(active)

    @mock.patch("contatori.management.commands.poll_snmp_devices.interroga_dispositivo")
    def test_command_poll_dispositivi(self, poll):
        device = DispositivoSNMP.objects.create(nome="Sensore", host="192.0.2.70")
        poll.return_value = RilevazioneSNMP(
            dispositivo=device, stato=StatoSNMP.OK, tempo_risposta_ms=12,
        )
        output = StringIO()
        call_command("poll_snmp_devices", stdout=output)
        poll.assert_called_once_with(device)
        self.assertIn("1 dispositivi", output.getvalue())
