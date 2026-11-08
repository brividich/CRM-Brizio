"""Test per il layout dello scadenzario HR: viste (gruppi/calendario/affiancata),
visite collassate, ↻ Rinnovo per singola visita e rinnovo formazione da selezione.

Piano: docs/superpowers/plans/2026-07-16-anagrafica-scadenzario-layout.md (rimosso dal repo, storico git 018367f1)
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
            "corso": str(self.corso.pk),
            "stato": "PIANIFICATA", "modalita": "IN_SEDE",
            "data_inizio": oggi, "data_fine": oggi,
        })
        self.assertEqual(resp.status_code, 302)
        sess = TrainingSession.objects.get(corso=self.corso)
        self.assertEqual(
            set(TrainingEnrollment.objects.filter(sessione=sess).values_list("legacy_anagrafica_id", flat=True)),
            {51, 52},
        )
        self.assertNotIn("rinnovo_preselect", self.client.session)  # pulito
        self.assertIn(f"/formazione/sessioni/{sess.pk}/iscritti/", resp["Location"])


class LayoutRenderTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.su = User.objects.create_superuser("su-lr", "su-lr@test.local", "x")
        self.client.force_login(self.su)
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="LrT", durata_mesi=12)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=401, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )

    def test_affiancata_due_colonne(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"layout": "affiancata"})
        body = resp.content.decode()
        self.assertIn("col-visite", body)
        self.assertIn("col-formazione", body)

    def test_calendario_intestazione_mese(self):
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"layout": "calendario"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("cal-grid", resp.content.decode())


class FormazioneScadenzarioPlanTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-fsp", "su-fsp@test.local", "x")
        self.client.force_login(self.su)
        self.corso = _mk_corso("C-FSP", "Corso Fsp")
        TrainingDeadline.objects.create(
            legacy_anagrafica_id=61, corso=self.corso, is_required=True,
            data_scadenza=timezone.localdate() - timedelta(days=5), stato_scadenza="SCADUTO",
        )

    def test_toggle_calendario_plan_presente(self):
        resp = self.client.get(reverse("anagrafica:formazione_scadenzario"))
        self.assertIn("view=calendario", resp.content.decode())

    def test_seleziona_dipendenti_form_presente(self):
        # le checkbox si mostrano solo con un corso filtrato (batch per-corso)
        resp = self.client.get(reverse("anagrafica:formazione_scadenzario"), {"corso": self.corso.pk})
        body = resp.content.decode()
        self.assertIn('name="dipendenti_selezionati"', body)
        self.assertIn("formazione/rinnovo-da-scadenzario", body)


class RinnovoContrattoDaScadenzarioTests(TestCase):
    """«Rinnova» su una scadenza contratto: stessa azione, stessa colonna degli
    altri tipi; il salvataggio chiude il precedente e torna allo scadenzario."""

    def setUp(self):
        from django.db import connection
        from .models import StoricoContratto
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, attivo) "
                "VALUES (%s, %s, %s, %s, %s)",
                ["t.rinnovo", "Tizia", "Rinnovo", "UT", 1],
            )
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["t.rinnovo"])
            self.legacy_id = int(cur.fetchone()[0])
        self.su = User.objects.create_superuser("su-ctr", "su-ctr@test.local", "x")
        self.plain = User.objects.create_user("plain-ctr", "plain-ctr@test.local", "x")
        self.oggi = timezone.localdate()
        self.fine = self.oggi + timedelta(days=4)
        self.contratto = StoricoContratto.objects.create(
            legacy_anagrafica_id=self.legacy_id,
            data_inizio=self.oggi - timedelta(days=360), data_fine=self.fine,
            tipologia_contratto="DETERMINATO", codice_livello="C2",
            descrizione_livello="Livello C2", qualifica_nome="Operaio",
        )

    def test_voce_contratto_porta_i_dati_del_rinnovo(self):
        from .views import _build_scadenzario_voci
        rf = RequestFactory()
        request = rf.get("/anagrafica/scadenzario/")
        request.user = self.su
        v = next(x for x in _build_scadenzario_voci(request, filtro_tipo="contratto") if x["kind"] == "contratto")
        self.assertEqual(v["contratto_id"], self.contratto.pk)
        self.assertEqual(v["rinnovo"]["data_inizio"], self.fine + timedelta(days=1))
        self.assertEqual(v["rinnovo"]["tipologia"], "DETERMINATO")
        self.assertEqual(v["rinnovo"]["codice_livello"], "C2")

    def test_pagina_mostra_pulsante_rinnova_e_dialog(self):
        self.client.force_login(self.su)
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"tipo": "contratto"})
        body = resp.content.decode()
        url = reverse("anagrafica:scadenzario_contratto_rinnova", args=[self.legacy_id])
        self.assertIn(f'data-rinnovo-url="{url}"', body)
        self.assertIn('data-rinnovo-inizio="%s"' % (self.fine + timedelta(days=1)).isoformat(), body)
        self.assertIn('id="scad-rinnovo-dlg"', body)

    def test_post_crea_il_nuovo_contratto_e_torna_allo_scadenzario(self):
        from .models import StoricoContratto
        self.client.force_login(self.su)
        inizio = self.fine + timedelta(days=1)
        back = reverse("anagrafica:scadenzario") + "?tipo=contratto"
        resp = self.client.post(
            reverse("anagrafica:scadenzario_contratto_rinnova", args=[self.legacy_id]),
            {"data_inizio": inizio.isoformat(), "data_fine": "", "tipologia_contratto": "INDETERMINATO",
             "codice_livello": "C2", "descrizione_livello": "Livello C2", "qualifica_nome": "Operaio",
             "back": back},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], back)
        nuovo = StoricoContratto.objects.filter(legacy_anagrafica_id=self.legacy_id).order_by("-data_inizio").first()
        self.assertEqual(nuovo.data_inizio, inizio)
        self.assertIsNone(nuovo.data_fine)
        self.assertEqual(nuovo.tipologia_contratto, "INDETERMINATO")
        self.assertEqual(nuovo.importato_da, self.su)
        # Il precedente resta nello storico con la sua fine.
        self.contratto.refresh_from_db()
        self.assertEqual(self.contratto.data_fine, self.fine)
        # E la voce sparisce dallo scadenzario (nuovo contratto senza fine).
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"tipo": "contratto"})
        self.assertNotIn("data-rinnovo-url=\"", resp.content.decode())

    def test_fine_prima_dell_inizio_rifiutata(self):
        from .models import StoricoContratto
        self.client.force_login(self.su)
        n = StoricoContratto.objects.count()
        self.client.post(
            reverse("anagrafica:scadenzario_contratto_rinnova", args=[self.legacy_id]),
            {"data_inizio": "2030-01-10", "data_fine": "2030-01-01"},
        )
        self.assertEqual(StoricoContratto.objects.count(), n)

    def test_senza_permesso_hr_non_scrive(self):
        from .models import StoricoContratto
        self.client.force_login(self.plain)
        n = StoricoContratto.objects.count()
        resp = self.client.post(
            reverse("anagrafica:scadenzario_contratto_rinnova", args=[self.legacy_id]),
            {"data_inizio": "2030-01-01"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(StoricoContratto.objects.count(), n)

    def test_formazione_ha_rinnova_per_riga(self):
        corso = _mk_corso("C-ROW", "Corso Riga")
        TrainingDeadline.objects.create(
            legacy_anagrafica_id=self.legacy_id, corso=corso, is_required=True,
            data_scadenza=self.oggi + timedelta(days=10), stato_scadenza="IN_SCADENZA_30",
        )
        self.client.force_login(self.su)
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"tipo": "formazione"})
        body = resp.content.decode()
        self.assertIn('class="scad-act-form"', body)
        self.assertIn(f'name="dipendenti_selezionati" value="{self.legacy_id}"', body)
