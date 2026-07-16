"""Test per il layout dello scadenzario HR: viste (gruppi/calendario/affiancata),
visite collassate, ↻ Rinnovo per singola visita e rinnovo formazione da selezione.

Piano: docs/superpowers/plans/2026-07-16-anagrafica-scadenzario-layout.md
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from .models import TipoVisitaMedica, VisitaMedica
from .models_formazione import TrainingCourse, TrainingDeadline, TrainingPlan

User = get_user_model()


def _mk_corso(codice, titolo, **kw):
    """Corso formativo minimo valido: ``piano`` e ``durata_ore_teorica`` sono
    NOT NULL, quindi vanno sempre forniti (il piano è condiviso per codice)."""
    piano, _ = TrainingPlan.objects.get_or_create(
        codice="P-SCADLAY", defaults={"nome": "Piano test scadenzario layout"}
    )
    kw.setdefault("durata_ore_teorica", 8)
    kw.setdefault("is_active", True)
    return TrainingCourse.objects.create(piano=piano, codice=codice, titolo=titolo, **kw)


class VociScadenzarioIdsTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.su = User.objects.create_superuser("su-voci", "su-voci@test.local", "x")
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="VociT", durata_mesi=12)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=201, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),  # scaduta
        )
        self.corso = _mk_corso("C-VOCI", "Corso Voci")
        TrainingDeadline.objects.create(
            legacy_anagrafica_id=201, corso=self.corso, is_required=True,
            data_scadenza=self.oggi + timedelta(days=10), stato_scadenza="IN_SCADENZA_30",
        )

    def _voci(self, **kw):
        from .views import _build_scadenzario_voci
        rf = RequestFactory()
        request = rf.get("/anagrafica/scadenzario/")
        request.user = self.su
        return _build_scadenzario_voci(request, **kw)

    def test_voce_visita_ha_tipo_id(self):
        v = next(x for x in self._voci(filtro_tipo="visita") if x["kind"] == "visita")
        self.assertEqual(v["tipo_id"], self.tipo.pk)

    def test_voce_formazione_ha_corso_id(self):
        f = next(x for x in self._voci(filtro_tipo="formazione") if x["kind"] == "formazione")
        self.assertEqual(f["corso_id"], self.corso.pk)

    def test_gruppo_visita_ha_tipo_id(self):
        from .views import _raggruppa_scadenze_per_tipo
        gruppi = _raggruppa_scadenze_per_tipo(self._voci(filtro_tipo="visita"))
        g = next(x for x in gruppi if x["kind"] == "visita")
        self.assertEqual(g["tipo_id"], self.tipo.pk)


class LayoutContextTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.su = User.objects.create_superuser("su-lay", "su-lay@test.local", "x")
        self.client.force_login(self.su)

    def test_layout_default_gruppi(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"))
        self.assertEqual(resp.context["layout"], "gruppi")

    def test_layout_ignora_valore_ignoto(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"layout": "pippo"})
        self.assertEqual(resp.context["layout"], "gruppi")

    def test_layout_affiancata_espone_colonne(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"layout": "affiancata"})
        self.assertEqual(resp.context["layout"], "affiancata")
        self.assertIn("voci_visite", resp.context)
        self.assertIn("voci_formazione", resp.context)

    def test_layout_calendario_espone_griglia(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"layout": "calendario"})
        self.assertEqual(resp.context["layout"], "calendario")
        self.assertIn("cal_settimane", resp.context)
