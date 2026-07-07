"""MOD.128 MPQ — bidirezionalità Formazione: i corsi richiesti da un processo
diventano un obbligo reale (copertura/gap + cache scadenze).

Verifica l'helper condiviso e i due punti d'innesto (``_legacy_ids_pertinenti``
per la copertura, ``refresh_deadlines`` per lo scadenzario/conformità).
Nessun dato reale.
"""
from __future__ import annotations

from django.test import TestCase

from .models import (
    AbilitazioneProcesso,
    ClienteQualificante,
    ProcessoQualificato,
    TipoQualifica,
    TrainingCourse,
    TrainingDeadline,
    TrainingPlan,
)


def _corso(codice="C1"):
    plan = TrainingPlan.objects.create(codice=f"PL-{codice}", nome="Piano")
    return TrainingCourse.objects.create(
        piano=plan, codice=codice, titolo=f"Corso {codice}", durata_ore_teorica=1)


def _processo_con_corso(corso, *, legacy_ids=(77,), stato=None):
    cli = ClienteQualificante.objects.create(nome=f"Cli {corso.codice}")
    p = ProcessoQualificato.objects.create(nome=f"Proc {corso.codice}", cliente=cli)
    p.corsi_richiesti.add(corso)
    st = stato or AbilitazioneProcesso.STATO_ATTIVA
    for lid in legacy_ids:
        AbilitazioneProcesso.objects.create(legacy_anagrafica_id=lid, processo=p, stato=st)
    return p


class HelperTests(TestCase):
    def test_abilitati_attivi_richiesti(self):
        from .services.mpq_formazione import legacy_ids_richiesti_da_processo
        c = _corso()
        _processo_con_corso(c, legacy_ids=(77, 88))
        self.assertEqual(legacy_ids_richiesti_da_processo(c.id), {77, 88})

    def test_sospesa_e_esterni_esclusi(self):
        from .services.mpq_formazione import legacy_ids_richiesti_da_processo
        c = _corso("C2")
        p = _processo_con_corso(c, legacy_ids=(77,))
        # sospesa esclusa
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=90, processo=p, stato=AbilitazioneProcesso.STATO_SOSPESA)
        # esterno (legacy_id=0) escluso
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=0, processo=p, nominativo_esterno="Ext")
        self.assertEqual(legacy_ids_richiesti_da_processo(c.id), {77})

    def test_nessun_processo(self):
        from .services.mpq_formazione import legacy_ids_richiesti_da_processo
        c = _corso("C3")
        self.assertEqual(legacy_ids_richiesti_da_processo(c.id), set())


class CoperturaTests(TestCase):
    def test_pertinenti_include_processo(self):
        from .services.training_eligibility import _legacy_ids_pertinenti
        c = _corso("C4")
        _processo_con_corso(c, legacy_ids=(77,))
        dipendenti = {77: {"mansione": "", "cognome": "R", "nome": "M"}}
        ids, has_rules = _legacy_ids_pertinenti(c, dipendenti)
        self.assertIn(77, ids)
        self.assertTrue(has_rules)


class ScadenzeTests(TestCase):
    def test_refresh_crea_deadline_obbligatoria(self):
        from .services.training_deadline_service import refresh_deadlines
        c = _corso("C5")
        _processo_con_corso(c, legacy_ids=(77,))
        refresh_deadlines(corso_id=c.id)
        d = TrainingDeadline.objects.get(legacy_anagrafica_id=77, corso=c)
        self.assertTrue(d.is_required)
        self.assertEqual(d.stato_scadenza, "MAI_FREQUENTATO")

    def test_refresh_non_tocca_altri(self):
        from .services.training_deadline_service import refresh_deadlines
        c = _corso("C6")  # corso senza processo
        refresh_deadlines(corso_id=c.id)
        self.assertFalse(TrainingDeadline.objects.filter(corso=c).exists())


class CourseFormProcessiTests(TestCase):
    """Il form corso espone i processi qualificati (reverse M2M) e raggruppa la
    qualifica per tipologia."""

    def test_campo_processi_presente(self):
        from .forms import TrainingCourseForm
        self.assertIn("processi_richiedenti", TrainingCourseForm().fields)

    def test_qualifica_raggruppata_per_tipologia(self):
        from .forms import TrainingCourseForm
        TipoQualifica.objects.create(nome="Q Sic", categoria=TipoQualifica.CAT_SICUREZZA)
        TipoQualifica.objects.create(nome="Q Prof", categoria=TipoQualifica.CAT_PROFESSIONALE)
        choices = TrainingCourseForm().fields["qualifica"].widget.choices
        optgroups = [c for c in choices if isinstance(c, tuple) and isinstance(c[1], list)]
        self.assertGreaterEqual(len(optgroups), 2)  # ≥2 optgroup (categorie)

    def test_salva_processi_reverse_m2m(self):
        from .forms import TrainingCourseForm
        c = _corso("C7")
        cli = ClienteQualificante.objects.create(nome="Cli form")
        p = ProcessoQualificato.objects.create(nome="Proc form", cliente=cli)
        form = TrainingCourseForm(instance=c)
        form.cleaned_data = {"processi_richiedenti": [p]}
        form.salva_processi(c)
        self.assertIn(p, c.processi_richiedenti.all())
