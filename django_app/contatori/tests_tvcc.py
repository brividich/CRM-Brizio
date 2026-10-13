"""Videosorveglianza TVCC sul monitor SNMP: preset TVT, MAC, intervalli e retention."""
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from assets.services.mac import normalizza_mac
from automazioni.schedules import spec_by_name
from contatori import tasks
from contatori.forms import ImpostazioniSNMPForm
from contatori.models import (
    ColonnaProfiloSNMP, DispositivoSNMP, ImpostazioniSNMP, ProfiloSNMP, RilevazioneSNMP, StatoSNMP,
)
from contatori.services import applica_profilo_dispositivo, interroga_dispositivo
from contatori.snmp import SNMPError, aggrega_colonna

MAC_BYTES = bytes.fromhex("00189a0b0c0d")
IF_PHYS = "1.3.6.1.2.1.2.2.1.6"


class MacTests(TestCase):
    def test_normalizza_forme_diverse(self):
        for valore in ("00:18:9A:0B:0C:0D", "00-18-9a-0b-0c-0d", "0018.9a0b.0c0d", "00189A0B0C0D",
                       "0x00189a0b0c0d", MAC_BYTES):
            self.assertEqual(normalizza_mac(valore), "00:18:9a:0b:0c:0d", valore)

    def test_scarta_valori_non_mac(self):
        for valore in (None, "", "00:00:00:00:00:00", b"\x00" * 6, b"", "ciao", "00:18:9a:0b:0c", "zz189a0b0c0d"):
            self.assertEqual(normalizza_mac(valore), "", valore)

    def test_primo_valido_salta_il_loopback(self):
        self.assertEqual(aggrega_colonna([b"", b"\x00" * 6, MAC_BYTES], "VALIDO"), MAC_BYTES)
        self.assertEqual(aggrega_colonna(["", "7"], "VALIDO"), "7")
        with self.assertRaises(SNMPError):
            aggrega_colonna([b"", b"\x00" * 6], "VALIDO")


class PresetTvtTests(TestCase):
    def test_preset_seminati_non_verificati_senza_riconoscimento(self):
        for slug, categoria in (("tvt-nvr", "TVCC_NVR"), ("tvt-ipc", "TVCC_CAMERA")):
            profilo = ProfiloSNMP.objects.get(slug=slug)
            self.assertEqual(profilo.categoria, categoria)
            self.assertEqual((profilo.sys_object_id_prefix, profilo.sys_descr_pattern, profilo.oid_riconoscimento),
                             ("", "", ""))
            self.assertFalse(profilo.colonne.filter(verificata=True).exists())
            self.assertFalse(profilo.colonne.exclude(soglia_warning_max=None).exists())
            # Nessun OID privato: solo rami MIB standard (mib-2) e UCD di net-snmp.
            for oid in profilo.colonne.values_list("oid", flat=True):
                self.assertTrue(oid.startswith(("1.3.6.1.2.1.", "1.3.6.1.4.1.2021.")), oid)

    def test_telecamera_solo_if_mib_attive_nvr_risorse_spente(self):
        ipc = ProfiloSNMP.objects.get(slug="tvt-ipc")
        self.assertTrue(all(c.oid.startswith("1.3.6.1.2.1.2.2.1.") for c in ipc.colonne.filter(attiva=True)))
        nvr = ProfiloSNMP.objects.get(slug="tvt-nvr")
        spente = set(nvr.colonne.filter(attiva=False).values_list("oid", flat=True))
        self.assertIn("1.3.6.1.4.1.2021.9.1.9", spente)
        self.assertIn("1.3.6.1.2.1.25.3.3.1.2", spente)
        mac = nvr.colonne.get(oid=IF_PHYS)
        self.assertEqual((mac.tipo_valore, mac.aggregazione), ("MAC", "VALIDO"))

    def test_rilevazione_telecamera_salva_mac_normalizzato(self):
        dispositivo = DispositivoSNMP.objects.create(nome="Telecamera QA", host="192.0.2.61")
        applica_profilo_dispositivo(dispositivo, ProfiloSNMP.objects.get(slug="tvt-ipc"))
        self.assertEqual(dispositivo.categoria, DispositivoSNMP.Categoria.TVCC_TELECAMERA)

        def finto(host, specifiche, **kwargs):
            valori = {"1.3.6.1.2.1.1.1.0": b"Linux synthetic-ipc"}
            for spec in specifiche:
                oid = spec["oid"]
                if oid == IF_PHYS:
                    valori[oid] = aggrega_colonna([b"", MAC_BYTES], spec["aggregazione"])
                elif oid.startswith("1.3.6.1.2.1.2.2.1."):
                    valori[oid] = 100_000_000 if oid.endswith(".5") else 0
            return valori, {}

        with mock.patch("contatori.snmp.leggi_specifiche", side_effect=finto):
            rilevazione = interroga_dispositivo(dispositivo)
        self.assertEqual(rilevazione.stato, StatoSNMP.OK)
        valori = {v.sonda.nome: v for v in rilevazione.valori.all()}
        self.assertEqual(valori["MAC"].valore_testo, "00:18:9a:0b:0c:0d")
        self.assertEqual(valori["Velocita collegamento"].valore_display, "100 Mbit/s")


class IntervalliTvccTests(TestCase):
    def setUp(self):
        cache.clear()
        self.adesso = timezone.now()

    def tearDown(self):
        cache.clear()

    def _dispositivo(self, nome, host, categoria, minuti_fa):
        return DispositivoSNMP.objects.create(
            nome=nome, host=host, categoria=categoria,
            snmp_ultimo_controllo=self.adesso - timedelta(minutes=minuti_fa) if minuti_fa is not None else None,
        )

    def test_intervalli_predefiniti(self):
        cat = DispositivoSNMP.Categoria
        dovuti = {
            self._dispositivo("cam recente", "192.0.2.71", cat.TVCC_TELECAMERA, 10).pk: False,
            self._dispositivo("cam scaduta", "192.0.2.72", cat.TVCC_TELECAMERA, 29).pk: True,
            self._dispositivo("cam mai letta", "192.0.2.73", cat.TVCC_TELECAMERA, None).pk: True,
            self._dispositivo("nvr recente", "192.0.2.74", cat.TVCC_NVR, 1).pk: False,
            self._dispositivo("nvr scaduto", "192.0.2.75", cat.TVCC_NVR, 4).pk: True,
            # Gli altri apparati restano a ogni giro, come prima.
            self._dispositivo("ups", "192.0.2.76", cat.UPS, 1).pk: True,
        }
        scelti = set(tasks._dispositivi_da_interrogare(self.adesso))
        for pk, atteso in dovuti.items():
            self.assertEqual(pk in scelti, atteso, DispositivoSNMP.objects.get(pk=pk).nome)

    def test_intervallo_modificabile_da_impostazioni(self):
        cfg = ImpostazioniSNMP.get_solo()
        cfg.tvcc_intervallo_telecamere = 60
        cfg.save()
        cam = self._dispositivo("cam", "192.0.2.77", DispositivoSNMP.Categoria.TVCC_TELECAMERA, 40)
        self.assertNotIn(cam.pk, tasks._dispositivi_da_interrogare(self.adesso))

    @mock.patch("contatori.tasks.async_task")
    def test_run_poll_accoda_solo_dovuti(self, enqueue):
        self._dispositivo("cam recente", "192.0.2.78", DispositivoSNMP.Categoria.TVCC_TELECAMERA, 5)
        self.assertEqual(tasks.run_poll_snmp(), {"accodati": 0})
        enqueue.assert_not_called()

    def test_form_impostazioni_minimi(self):
        dati = {"community": "", "port": 161, "timeout": 3, "version": "v1",
                "tvcc_intervallo_nvr": 2, "tvcc_intervallo_telecamere": 30, "tvcc_retention_giorni": 0}
        form = ImpostazioniSNMPForm(dati, instance=ImpostazioniSNMP.get_solo())
        self.assertFalse(form.is_valid())
        self.assertEqual(set(form.errors), {"tvcc_intervallo_nvr", "tvcc_retention_giorni"})


class RetentionTvccTests(TestCase):
    def _rilevazione(self, dispositivo, giorni_fa):
        return RilevazioneSNMP.objects.create(
            dispositivo=dispositivo, stato=StatoSNMP.OK,
            rilevata_il=timezone.now() - timedelta(days=giorni_fa),
        )

    def test_cancella_solo_tvcc_oltre_retention(self):
        cam = DispositivoSNMP.objects.create(nome="cam", host="192.0.2.81",
                                             categoria=DispositivoSNMP.Categoria.TVCC_TELECAMERA)
        nvr = DispositivoSNMP.objects.create(nome="nvr", host="192.0.2.82",
                                             categoria=DispositivoSNMP.Categoria.TVCC_NVR)
        ups = DispositivoSNMP.objects.create(nome="ups", host="192.0.2.83",
                                             categoria=DispositivoSNMP.Categoria.UPS)
        vecchie = [self._rilevazione(cam, 20), self._rilevazione(nvr, 15)]
        restano = [self._rilevazione(cam, 2), self._rilevazione(nvr, 13), self._rilevazione(ups, 60)]
        esito = tasks.pulisci_rilevazioni_tvcc()
        self.assertEqual(esito, {"giorni": 14, "cancellate": 2})
        self.assertFalse(RilevazioneSNMP.objects.filter(pk__in=[r.pk for r in vecchie]).exists())
        self.assertEqual(RilevazioneSNMP.objects.filter(pk__in=[r.pk for r in restano]).count(), 3)

    def test_giorni_da_impostazioni(self):
        cam = DispositivoSNMP.objects.create(nome="cam", host="192.0.2.84",
                                             categoria=DispositivoSNMP.Categoria.TVCC_TELECAMERA)
        self._rilevazione(cam, 5)
        ImpostazioniSNMP.objects.filter(pk=ImpostazioniSNMP.get_solo().pk).update(tvcc_retention_giorni=3)
        self.assertEqual(tasks.pulisci_rilevazioni_tvcc()["cancellate"], 1)

    def test_schedule_notturna_registrata(self):
        spec = spec_by_name("contatori_pulizia_tvcc")
        self.assertEqual(spec["func"], "contatori.tasks.pulisci_rilevazioni_tvcc")
        self.assertEqual(spec["cron"], "40 3 * * *")


class ReadOnlyTvccTests(TestCase):
    def test_nessuna_scrittura_snmp_nel_motore(self):
        """Il monitor TVCC passa dal motore esistente, che non deve mai usare SET."""
        from pathlib import Path

        import contatori

        base = Path(contatori.__file__).parent
        for nome in ("snmp.py", "services.py", "tasks.py", "printer_snmp.py"):
            sorgente = (base / nome).read_text(encoding="utf-8")
            for vietato in (".set(", "multiset(", "bulkset(", "SetRequest"):
                self.assertNotIn(vietato, sorgente, f"{nome}: {vietato}")

    def test_colonna_mac_accetta_le_nuove_scelte(self):
        profilo = ProfiloSNMP.objects.get(slug="tvt-ipc")
        colonna = ColonnaProfiloSNMP(profilo=profilo, nome="MAC bis", oid="1.3.6.1.2.1.2.2.1.6.2",
                                     tipo_valore="MAC", aggregazione="VALIDO")
        colonna.full_clean()
