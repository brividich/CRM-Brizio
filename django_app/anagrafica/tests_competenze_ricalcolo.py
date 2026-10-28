"""Livelli sulle mansioni con competenze: ricalcolo automatico e matrice (28/10/2026). Dati sintetici."""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.urls import reverse

from .models import (
    AbilitazioneMacchina, AbilitazioneMacchinaStorico, AbilitazioneMacchinaVoce, DipendenteQualifica,
    SkillMatrixConfig, TipoQualifica, ValutazioneCompetenzaStorico,
)
from .services import competenze_ricalcolo as ric
from .services import mansionario_competenze as comp
from .services import mansionario_struttura as svc
from .tests_struttura import _Base


class RicalcoloCompetenzeTests(_Base):
    def setUp(self):
        super().setUp()
        self.patentino = TipoQualifica.objects.create(nome="Patentino sbavatore sintetico")
        self.uso = comp.salva_competenza(self.processo, nome="Uso sbavatore", livello_minimo="U", bloccante=True,
                                         qualifica_id=self.patentino.pk)
        self.setup = comp.salva_competenza(self.processo, nome="Set-up", livello_minimo="L")

    def _ab(self, persona=None):
        return AbilitazioneMacchina.objects.get(legacy_anagrafica_id=(persona or self.p1).pk, competenza=self.processo)

    def test_assegna_da_valutare_senza_requisito_scende_sotto_soglia(self):
        with self.captureOnCommitCallbacks(execute=True):
            svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="U", user=self.admin)
        ab = self._ab()
        self.assertFalse(AbilitazioneMacchinaVoce.objects.filter(abilitazione=ab).exists())  # resta «da valutare»
        self.assertEqual(ab.livello, "L")  # non abilitato: sotto la soglia U, non operativo
        self.assertIn("partenza U → L", AbilitazioneMacchinaStorico.objects.filter(
            competenza=self.processo).order_by("-id").first().note)

    def test_qualifica_ottenuta_rialza_il_livello_da_sola(self):
        ab = svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="I")
        comp.registra_livelli(ab, {self.uso.pk: "U", self.setup.pk: "U"})
        self.assertEqual(self._ab().livello, "I")  # senza patentino la competenza conta I
        with self.captureOnCommitCallbacks(execute=True):
            q = DipendenteQualifica.objects.create(legacy_anagrafica_id=self.p1.pk, tipo=self.patentino)
        self.assertEqual(self._ab().livello, "U")
        ultimo = AbilitazioneMacchinaStorico.objects.filter(competenza=self.processo).order_by("-id").first()
        self.assertEqual(ultimo.fonte, AbilitazioneMacchinaStorico.FONTE_AUTOMATICO)
        self.assertIn("qualifiche della persona cambiate", ultimo.note)
        with self.captureOnCommitCallbacks(execute=True):
            q.delete()
        self.assertEqual(self._ab().livello, "I")

    def test_nuova_competenza_bloccante_abbassa_chi_era_operativo(self):
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.p1.pk, tipo=self.patentino)
        ab = svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="I")
        comp.registra_livelli(ab, {self.uso.pk: "O", self.setup.pk: "O"})
        self.assertEqual(self._ab().livello, "O")
        with self.captureOnCommitCallbacks(execute=True):
            comp.salva_competenza(self.processo, nome="Controllo bave", livello_minimo="U", bloccante=True)
        self.assertEqual(self._ab().livello, "I")  # la nuova bloccante non è valutata: niente operativo

    def test_regole_cambiate_ricalcolano_tutti(self):
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.p1.pk, tipo=self.patentino)
        ab = svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="O")
        comp.registra_livelli(ab, {self.uso.pk: "O", self.setup.pk: "L"})
        self.assertEqual(self._ab().livello, "U")  # media O+L = U, tetto bloccante O
        config = SkillMatrixConfig.get_instance()
        config.regola_multivoce = SkillMatrixConfig.REGOLA_MIN
        with self.captureOnCommitCallbacks(execute=True):
            config.save()
        self.assertEqual(self._ab().livello, "L")

    def test_mansione_senza_competenze_non_si_tocca(self):
        svc.assegna(self.fresa, legacy_anagrafica_id=self.p1.pk, livello="O")
        self.assertEqual(ric.ricalcola(None)["cambiate"], 0)
        self.assertEqual(AbilitazioneMacchina.objects.get(competenza=self.fresa).livello, "O")

    def test_comando_in_prova_non_scrive_e_ricalcolo_notturno(self):
        from .services.scadenze import ricalcola_tutto

        svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="U")
        AbilitazioneMacchina.objects.filter(competenza=self.processo).update(livello="O")  # disallineato a mano
        out = StringIO()
        call_command("ricalcola_livelli_competenze", stdout=out)
        self.assertIn("O → L", out.getvalue())
        self.assertEqual(self._ab().livello, "O")
        self.assertEqual(ricalcola_tutto([self.p1.pk])["competenze"]["cambiate"], 1)
        self.assertEqual(self._ab().livello, "L")

    def test_cella_della_matrice(self):
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.p1.pk, tipo=self.patentino)
        ab = svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="I")
        pagina = self.client.get(reverse("anagrafica:mansionario_mansione", args=[self.processo.pk]))
        url = reverse("anagrafica:mansionario_voce_livello", args=[self.processo.pk, ab.pk, self.uso.pk])
        self.assertContains(pagina, url)
        self.client.post(url, {"livello": "O"})
        self.client.post(reverse("anagrafica:mansionario_voce_livello", args=[self.processo.pk, ab.pk, self.setup.pk]),
                         {"livello": "U"})
        ab.refresh_from_db()
        self.assertEqual(ab.livello, "U")
        self.assertTrue(ValutazioneCompetenzaStorico.objects.filter(voce=self.uso, livello_prima="", livello="O").exists())
        n = ValutazioneCompetenzaStorico.objects.count()
        self.client.post(url, {"livello": "O"})  # stesso livello: niente scatto
        self.assertEqual(ValutazioneCompetenzaStorico.objects.count(), n)

    def test_cella_senza_permesso(self):
        from django.contrib.auth import get_user_model

        ab = svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="I")
        self.client.force_login(get_user_model().objects.create_user("cmp_nessuno", "n@example.invalid", "x"))
        self.client.post(reverse("anagrafica:mansionario_voce_livello", args=[self.processo.pk, ab.pk, self.uso.pk]),
                         {"livello": "O"})
        self.assertFalse(AbilitazioneMacchinaVoce.objects.filter(abilitazione=ab).exists())
