"""Il «Caporeparto» copiato nella scheda segue la regola unica area → reparto.

Salvare un reparto scriveva il suo caporeparto su tutti i membri, anche su
quelli di un'area con un responsabile proprio e sul capo stesso; cambiare il
responsabile di un'area non arrivava alle schede. Scheda e digest mattutino
leggono la copia, le assenze calcolano dal vivo: le due cose divergevano.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AreaAziendale, DipendenteAnagraficaAziendale, Reparto
from .services.reparto_canonico import riallinea_capo_schede

User = get_user_model()

CAPO_REPARTO = 501
RESP_AREA = 502
OPERAIO_AREA = 601
OPERAIO_REPARTO = 602


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RiallineaCapoSchedeTests(TestCase):
    def setUp(self):
        self.rep = Reparto.objects.create(nome="Fresatura", caporeparto_legacy_id=CAPO_REPARTO)
        self.area = AreaAziendale.objects.create(nome="IN1", reparto=self.rep, responsabile_legacy_id=RESP_AREA)
        self.area_senza_resp = AreaAziendale.objects.create(nome="IN2", reparto=self.rep)
        for legacy_id, area in (
            (OPERAIO_AREA, self.area),
            (OPERAIO_REPARTO, self.area_senza_resp),
            (CAPO_REPARTO, self.area_senza_resp),
        ):
            DipendenteAnagraficaAziendale.objects.create(
                legacy_anagrafica_id=legacy_id, area="Fresatura", area_aziendale=area, caporeparto_legacy_id=999,
            )

    def _capo(self, legacy_id):
        return DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=legacy_id).caporeparto_legacy_id

    def test_reparto_area_con_responsabile_vince(self):
        riallinea_capo_schede(reparto=self.rep)
        self.assertEqual(self._capo(OPERAIO_AREA), RESP_AREA)
        self.assertEqual(self._capo(OPERAIO_REPARTO), CAPO_REPARTO)

    def test_il_capo_non_e_capo_di_se_stesso(self):
        riallinea_capo_schede(reparto=self.rep)
        self.assertIsNone(self._capo(CAPO_REPARTO))

    def test_cambio_responsabile_area_arriva_alle_schede(self):
        riallinea_capo_schede(reparto=self.rep)
        self.area.responsabile_legacy_id = 777
        self.area.save()
        self.assertEqual(riallinea_capo_schede(area=self.area), 1)
        self.assertEqual(self._capo(OPERAIO_AREA), 777)
        self.assertEqual(self._capo(OPERAIO_REPARTO), CAPO_REPARTO)

    def test_area_senza_responsabile_ripiega_sul_reparto(self):
        self.area.responsabile_legacy_id = None
        self.area.save()
        riallinea_capo_schede(area=self.area)
        self.assertEqual(self._capo(OPERAIO_AREA), CAPO_REPARTO)

    def test_scheda_senza_area_usa_il_testo_del_reparto(self):
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=603, area="fresatura")
        riallinea_capo_schede(reparto=self.rep)
        self.assertEqual(self._capo(603), CAPO_REPARTO)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SalvataggioRepartoAreaTests(TestCase):
    """Le pagine Reparti e Aree aziendali usano la stessa regola."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="capo_schede_admin", email="c@x.local", password="x")
        self.client.force_login(self.admin)
        self.rep = Reparto.objects.create(nome="Saldatura", caporeparto_legacy_id=CAPO_REPARTO)
        self.area = AreaAziendale.objects.create(nome="SA1", reparto=self.rep, responsabile_legacy_id=RESP_AREA)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=OPERAIO_AREA, area="Saldatura", area_aziendale=self.area,
        )

    def test_capo_scelto_nel_form_riceve_la_responsabilita(self):
        """Dal 28/10/2026 il capo scelto nel form diventa chi ha la «Responsabilità» (sempre collegati)."""
        from anagrafica.models import RuoloOperativo
        from anagrafica.models_skillmatrix import AbilitazioneMacchina

        ruolo = RuoloOperativo.objects.create(nome="Caporeparto saldatura")
        self.client.post(reverse("anagrafica:area_edit", args=[self.rep.pk]), {
            "nome": "Saldatura", "is_active": "1", "caporeparto_legacy_id": "4242", "ruolo_responsabile": str(ruolo.pk),
        })
        self.rep.refresh_from_db()
        self.assertEqual(self.rep.caporeparto_legacy_id, 4242)
        self.assertEqual(self.rep.ruolo_responsabile_id, ruolo.pk)
        self.assertTrue(AbilitazioneMacchina.objects.filter(
            competenza__responsabilita_reparto=self.rep, legacy_anagrafica_id=4242, in_lista=True).exists())
        # Le Impostazioni non mandano il campo: il ruolo resta.
        self.client.post(reverse("anagrafica:area_edit", args=[self.rep.pk]), {"nome": "Saldatura", "is_active": "1"})
        self.rep.refresh_from_db()
        self.assertEqual(self.rep.ruolo_responsabile_id, ruolo.pk)
