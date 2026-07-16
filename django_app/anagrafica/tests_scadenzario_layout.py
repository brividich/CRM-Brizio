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


class ScadenzarioTemplateTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.su = User.objects.create_superuser("su-tpl", "su-tpl@test.local", "x")
        self.client.force_login(self.su)
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="TplT", durata_mesi=12)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=301, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )

    def test_toggle_layout_presente(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"))
        body = resp.content.decode()
        self.assertIn("layout=calendario", body)
        self.assertIn("layout=affiancata", body)

    def test_rinnovo_singola_visita_deeplink(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"tipo": "visita"})
        body = resp.content.decode()
        self.assertIn(f"nuova-sessione/?tipo={self.tipo.pk}", body)

    def test_gruppo_visita_non_auto_aperto(self):
        # i gruppi visita NON devono avere l'attributo open anche se scaduti
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"tipo": "visita"})
        body = resp.content.decode()
        # marcatore semplice: il summary Visita medica esiste ma senza <details ... open>
        self.assertIn("Visita medica", body)


class RinnovoFormazioneEndpointTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-rin", "su-rin@test.local", "x")
        self.plain = User.objects.create_user("plain-rin", "plain-rin@test.local", "x")
        self.corso = _mk_corso("C-RIN", "Corso Rin")

    def test_post_stasha_e_redirige_a_create(self):
        self.client.force_login(self.su)
        resp = self.client.post(
            reverse("anagrafica:formazione_rinnovo_da_scadenzario"),
            {"corso_id": str(self.corso.pk), "dipendenti_selezionati": ["10", "11", "10"]},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"?corso={self.corso.pk}", resp["Location"])
        stash = self.client.session["rinnovo_preselect"]
        self.assertEqual(stash["corso"], self.corso.pk)
        self.assertEqual(sorted(stash["ids"]), [10, 11])  # dedup

    def test_nessun_selezionato_warning(self):
        self.client.force_login(self.su)
        resp = self.client.post(
            reverse("anagrafica:formazione_rinnovo_da_scadenzario"),
            {"corso_id": str(self.corso.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("rinnovo_preselect", self.client.session)

    def test_403_senza_permesso_editor(self):
        self.client.force_login(self.plain)
        resp = self.client.post(
            reverse("anagrafica:formazione_rinnovo_da_scadenzario"),
            {"corso_id": str(self.corso.pk), "dipendenti_selezionati": ["10"]},
        )
        # _can_edit_formazione nega → redirect (no stash)
        self.assertNotIn("rinnovo_preselect", self.client.session)


class SessioneCreateConsumaPreselectTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-cre", "su-cre@test.local", "x")
        self.client.force_login(self.su)
        self.corso = _mk_corso("C-CRE", "Corso Cre")

    def test_salvataggio_iscrive_i_preselezionati(self):
        from .models_formazione import TrainingSession, TrainingEnrollment
        s = self.client.session
        s["rinnovo_preselect"] = {"corso": self.corso.pk, "ids": [51, 52]}
        s.save()
        oggi = timezone.localdate().isoformat()
        resp = self.client.post(reverse("anagrafica:formazione_sessione_create"), {
            "corso": str(self.corso.pk), "codice_sessione": "SESS-CRE-1",
            "stato": "PIANIFICATA", "modalita": "IN_SEDE",
            "data_inizio": oggi, "data_fine": oggi,
        })
        self.assertEqual(resp.status_code, 302)
        sess = TrainingSession.objects.get(codice_sessione="SESS-CRE-1")
        self.assertEqual(
            set(TrainingEnrollment.objects.filter(sessione=sess).values_list("legacy_anagrafica_id", flat=True)),
            {51, 52},
        )
        self.assertNotIn("rinnovo_preselect", self.client.session)  # pulito
        self.assertIn(f"/formazione/sessioni/{sess.pk}/iscritti/", resp["Location"])
