"""Indice di postura: una regola sola, stesso numero nella scheda del PC e nella mappa di «Da fare»."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import DispositivoIntune
from core.models import UserOnboarding
from security.models import (
    SecurityAlert,
    SecurityAsset,
    SecurityEventRecord,
    SecuritySource,
    SourceType,
    WatchGuardDispositivo,
    WatchGuardPatch,
)
from security.services import postura
from security.services.pc_overview import pc_scheda


class PunteggioTests(TestCase):
    def test_nessun_problema_vale_100(self):
        r = postura.punteggio({"backup": "ok", "wg": ("ok", "Attiva")})
        self.assertEqual((r["punteggio"], r["tono"], r["motivi"]), (100, "success", []))

    def test_tetti_e_soglie(self):
        r = postura.punteggio({"backup": "fallito", "alert": (3, 5), "cve": (40, 10), "wg": ("non_protetto", "Disattivata"),
                               "intune": ["disco non cifrato (BitLocker)"], "sistema": {"nome": "Windows 10 22H2", "fuori": True, "in_scadenza": False},
                               "patch": (10, 30)})
        punti = {m["testo"]: m["punti"] for m in r["motivi"]}
        self.assertEqual(punti["Ultimo backup fallito"], 25)
        self.assertEqual(punti["5 alert aperti"], 30)            # tetto
        self.assertEqual(punti["10 CVE gravi (KEV o CVSS ≥ 9)"], 25)  # tetto
        self.assertEqual(punti["30 altre CVE"], 10)               # tetto
        self.assertEqual(punti["30 patch mancanti (10 critiche)"], 15)
        self.assertEqual(r["punteggio"], 0)
        self.assertEqual(r["tono"], "critical")
        self.assertEqual(r["motivi"][0]["scheda"], "timeline")    # il motivo più pesante apre la sua sezione
        self.assertEqual(postura.tono_di(80), "success")
        self.assertEqual(postura.tono_di(79), "warning")
        self.assertEqual(postura.tono_di(49), "critical")


class MappaTests(TestCase):
    def setUp(self):
        cache.delete(postura.CACHE_MAPPA)
        user = get_user_model().objects.create(username="postura_user", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=user, completed=True)
        self.client.force_login(user)
        now = timezone.now()
        DispositivoIntune.objects.create(intune_id="p1", nome="PC-BUONO")
        DispositivoIntune.objects.create(intune_id="p2", nome="PC-MALE", problemi=[DispositivoIntune.PROBLEMA_NON_CIFRATO])
        WatchGuardDispositivo.objects.create(device_id="wb", host="pc-buono", protezione=1, motore_aggiornato=True, ultima_connessione=now)
        WatchGuardDispositivo.objects.create(device_id="wm", host="pc-male", protezione=2, ultima_connessione=now - timedelta(days=30))
        WatchGuardPatch.objects.create(device_id="wm", patch_id="x", host="pc-male", nome="Aggiornamento", criticita=201)
        src = SecuritySource.objects.create(name="Fonte test postura", source_type=SourceType.choices[0][0])
        asset = SecurityAsset.objects.create(hostname="PC-MALE.dominio.local", source=src)
        ev = SecurityEventRecord.objects.create(source=src, asset=asset, event_type="malware", fingerprint="f", dedup_hash="f")
        SecurityAlert.objects.create(source=src, event=ev, title="Malware", severity="critical", dedup_hash="a")

    def test_scheda_e_mappa_danno_lo_stesso_numero(self):
        m = postura.mappa(refresh=True)
        per_nome = {p["key"]: p for p in m["pcs"]}
        for nome in ("PC-BUONO", "PC-MALE"):
            self.assertEqual(per_nome[nome.lower()]["punteggio"], pc_scheda(nome)["rischio"]["punteggio"], nome)
        self.assertLess(per_nome["pc-male"]["punteggio"], per_nome["pc-buono"]["punteggio"])
        self.assertEqual(m["pcs"][0]["key"], "pc-male")  # dal peggiore
        self.assertEqual(sum(m["conta"].values()), len(m["pcs"]))

    def test_alert_contato_dal_nome_host_senza_dominio(self):
        self.assertEqual(postura.alert_per_pc()["pc-male"], (1, 1))
        self.assertEqual(postura.alert_per_pc("pc-male"), {"pc-male": (1, 1)})

    def test_riquadro_di_da_fare(self):
        dash = self.client.get(reverse("security:dashboard"))
        self.assertContains(dash, f'data-cy-lazy="{reverse("security:postura_mappa")}"')
        r = self.client.get(reverse("security:postura_mappa"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Indice medio")
        self.assertContains(r, "PC-MALE")
        self.assertContains(r, 'data-cy-map-tono="critical"')
