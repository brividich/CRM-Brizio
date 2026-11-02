"""«Segnalazioni urgenti»: contate per intero, non sulle prime 300 righe per tipo."""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from security.models import SecurityAlert, SecurityEventRecord, SecuritySource, Severity
from security.services import segnalazioni
from security.services.live_status import CACHE_KEY


class ContaUrgentiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.source = SecuritySource.objects.create(name="Casella", source_type="email", vendor="mailbox")
        self.n = 0

    def _alert(self, severity):
        self.n += 1
        event = SecurityEventRecord.objects.create(
            source=self.source, event_type="test", severity=severity, fingerprint=f"f{self.n}", dedup_hash=f"h{self.n}",
        )
        return SecurityAlert.objects.create(source=self.source, event=event, title=f"A{self.n}", severity=severity,
                                            dedup_hash=f"h{self.n}")

    def test_critico_vecchio_conta_anche_oltre_il_limite_della_lista(self):
        critico = self._alert(Severity.CRITICAL)
        for _ in range(3):
            self._alert(Severity.LOW)
        # Lista limitata a 2 righe per tipo: prima l'alert critico, aggiornato per
        # primo, restava fuori e il contatore lo perdeva.
        SecurityAlert.objects.filter(pk=critico.pk).update(updated_at=critico.updated_at.replace(year=2020))
        with mock.patch.object(segnalazioni, "PER_KIND_LIMIT", 2):
            self.assertEqual(segnalazioni.conta_urgenti(), 1)
            righe = segnalazioni.elenco(urgenti=True)
        self.assertEqual([r["pk"] for r in righe], [critico.pk])

    def test_la_barra_di_stato_si_svuota_quando_cambia_un_alert(self):
        cache.set(CACHE_KEY, {"items": []}, 60)
        with self.captureOnCommitCallbacks(execute=True):
            self._alert(Severity.HIGH)
        self.assertIsNone(cache.get(CACHE_KEY))
