"""Regressioni della reportistica: i dati riportati devono essere quelli veri.

Un test per ogni causa di dato errato trovata:
- anagrafiche doppie fuse (record agganciati all'id del doppione);
- stato della formazione letto dalla cache ``TrainingDeadline`` non aggiornata;
- requisiti di formazione da mansione / ruolo / regole, assenti dalla cache;
- visite valutate per tipo invece che per famiglia, visite superate;
- riassunti trattati come cessati, giorno di cessazione;
- query ``__in`` oltre il limite di parametri di SQL Server;
- registrazioni trovate ma non riportate senza spiegazione.

Dati sintetici: si sostituisce ``carica_dipendenti`` come in ``tests_reportistica``.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from anagrafica.models import (
    DipendenteQualifica,
    DipendenteRuoloOperativo,
    Mansione,
    ReportBlocco,
    ReportModello,
    RuoloOperativo,
    TipoQualifica,
    TipoVisitaMedica,
    TrainingCourse,
    TrainingDeadline,
    TrainingEmployeeRecord,
    TrainingPlan,
    TrainingRequirementRule,
    VisitaMedica,
)
from anagrafica.reportistica import calcoli, motore
from anagrafica.reportistica import sezioni as catalogo
from anagrafica.reportistica.dati import Contesto, Dipendente, Perimetro, a_blocchi, filtra_in

OGGI = timezone.localdate()


def _persone() -> list[Dipendente]:
    return [
        # 901 ha un'anagrafica doppia (951): i suoi dati possono stare su entrambi gli id.
        Dipendente(id=901, nominativo="ROSSI ANNA", reparto="Produzione", mansione="Saldatore",
                   data_assunzione=OGGI - timedelta(days=4000), ids=(901, 951)),
        Dipendente(id=902, nominativo="BIANCHI LUCA", reparto="Produzione", mansione="Operaio",
                   data_assunzione=OGGI - timedelta(days=300)),
        # Cessato da 10 giorni.
        Dipendente(id=903, nominativo="NERI PAOLO", reparto="Qualità", mansione="Tecnico",
                   data_assunzione=OGGI - timedelta(days=3000), data_cessazione=OGGI - timedelta(days=10)),
        # Riassunto: la vecchia cessazione e' rimasta sulla scheda.
        Dipendente(id=904, nominativo="VERDI GIULIA", reparto="Reparto Fantasma", mansione="Operaio",
                   data_assunzione=OGGI - timedelta(days=100), data_cessazione=OGGI - timedelta(days=400)),
    ]


class _Base(TestCase):
    def setUp(self):
        super().setUp()
        for target in ("anagrafica.reportistica.dati.carica_dipendenti",
                       "anagrafica.reportistica.forms.carica_dipendenti"):
            p = patch(target, side_effect=_persone)
            p.start()
            self.addCleanup(p.stop)

    def ctx(self, **perimetro) -> Contesto:
        return Contesto(date_from=OGGI - timedelta(days=365), date_to=OGGI,
                        perimetro=Perimetro.from_dict(perimetro), today=OGGI)

    def calcola(self, chiave: str, ctx: Contesto | None = None, **opzioni):
        ctx = ctx or self.ctx()
        return catalogo.get(chiave).calcola(ctx, opzioni)

    def corso(self, codice: str, *, validita: int = 12, attivo: bool = True) -> TrainingCourse:
        piano, _ = TrainingPlan.objects.get_or_create(codice="PT", defaults={"nome": "Piano test", "stato": "ATTIVO"})
        return TrainingCourse.objects.create(piano=piano, codice=codice, titolo=f"Corso {codice}",
                                             durata_ore_teorica=4, validita_mesi=validita, is_active=attivo)

    def completamento(self, lid: int, corso, giorni_fa: int, *, scadenza: date | None = None):
        return TrainingEmployeeRecord.objects.create(
            corso=corso, legacy_anagrafica_id=lid, data_completamento=OGGI - timedelta(days=giorni_fa),
            idoneo=True, data_scadenza=scadenza, course_code_snapshot=corso.codice, course_title_snapshot=corso.titolo,
        )


class OrganicoTest(_Base):
    def test_riassunto_con_vecchia_cessazione_e_in_forza(self):
        verdi = next(p for p in _persone() if p.id == 904)
        self.assertTrue(verdi.in_forza_al(OGGI))
        self.assertIsNone(verdi.cessazione_effettiva)
        self.assertIn(904, self.ctx().ids())

    def test_giorno_di_cessazione_ancora_in_organico(self):
        p = Dipendente(id=1, nominativo="X", data_assunzione=date(2020, 1, 1), data_cessazione=date(2025, 12, 31))
        self.assertTrue(p.in_forza_al(date(2025, 12, 31)))
        self.assertFalse(p.in_forza_al(date(2026, 1, 1)))

    def test_organigramma_non_perde_chi_e_fuori_catalogo(self):
        res = self.calcola("organigramma")
        fuori = [r for r in res.righe if r["livello"] == "Fuori catalogo"]
        self.assertEqual({r["reparto"] for r in fuori}, {"Produzione", "Reparto Fantasma"})
        self.assertEqual(sum(r["persone"] for r in fuori), 3)  # 901, 902, 904 (903 cessato)


class AnagraficheDoppieTest(_Base):
    def test_qualifica_sul_doppione_riportata_alla_persona(self):
        tipo = TipoQualifica.objects.create(nome="Patentino saldatura")
        DipendenteQualifica.objects.create(legacy_anagrafica_id=951, tipo=tipo,
                                           data_conseguimento=OGGI - timedelta(days=20),
                                           data_scadenza=OGGI + timedelta(days=300))
        res = self.calcola("personale_qualifiche")
        self.assertEqual([(r["nominativo"], r["qualifica"]) for r in res.righe], [("ROSSI ANNA", "Patentino saldatura")])
        matrice = self.calcola("matrice_qualifiche")
        riga = next(r for r in matrice.righe if r["nominativo"] == "ROSSI ANNA")
        self.assertEqual(riga[f"q{tipo.pk}"], "OK")

    def test_formazione_erogata_sul_doppione_conteggiata(self):
        corso = self.corso("C1")
        self.completamento(951, corso, 30)
        res = self.calcola("formazione_erogata")
        self.assertEqual([r["voce"] for r in res.righe], ["ROSSI ANNA"])

    def test_rinnovo_su_id_diverso_vale_il_piu_recente(self):
        tipo = TipoQualifica.objects.create(nome="Carrellista")
        DipendenteQualifica.objects.create(legacy_anagrafica_id=901, tipo=tipo,
                                           data_conseguimento=OGGI - timedelta(days=2000),
                                           data_scadenza=OGGI - timedelta(days=200))
        DipendenteQualifica.objects.create(legacy_anagrafica_id=951, tipo=tipo,
                                           data_conseguimento=OGGI - timedelta(days=100),
                                           data_scadenza=OGGI + timedelta(days=1000))
        res = self.calcola("personale_qualifiche")
        self.assertEqual([r["stato"] for r in res.righe], ["Valida"])


class FormazioneAllaDataTest(_Base):
    def test_cache_stantia_non_inganna_il_report(self):
        corso = self.corso("C-SCAD")
        rule = TrainingRequirementRule.objects.create(corso=corso, legacy_anagrafica_id=902)
        self.completamento(902, corso, 400, scadenza=OGGI - timedelta(days=35))
        # La cache dice ancora «valido» (ricalcolo mai rifatto).
        TrainingDeadline.objects.create(corso=corso, legacy_anagrafica_id=902, requirement_rule=rule,
                                        data_scadenza=OGGI - timedelta(days=35), stato_scadenza="VALIDO",
                                        is_required=True)
        res = self.calcola("personale_formazione")
        self.assertEqual([r["stato"] for r in res.righe], ["Scaduta"])

    def test_requisito_da_mansione_compare_anche_senza_cache(self):
        corso = self.corso("C-SALD")
        mansione = Mansione.objects.create(nome="Saldatore")
        TrainingRequirementRule.objects.create(corso=corso, mansione=mansione)
        res = self.calcola("personale_formazione")
        righe = [(r["nominativo"], r["stato"]) for r in res.righe]
        self.assertEqual(righe, [("ROSSI ANNA", "Mai frequentata")])
        self.assertIn("Saldatore", res.righe[0]["origine"])

    def test_requisito_da_ruolo_operativo_e_regole_non_in_vigore(self):
        corso = self.corso("C-RUOLO")
        ruolo = RuoloOperativo.objects.create(nome="Preposto")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=902, ruolo=ruolo)
        TrainingRequirementRule.objects.create(corso=corso, ruolo_operativo=ruolo)
        scaduta = self.corso("C-VECCHIA")
        TrainingRequirementRule.objects.create(corso=scaduta, legacy_anagrafica_id=902,
                                               data_fine_validita=OGGI - timedelta(days=1))
        spenta = self.corso("C-SPENTA")
        TrainingRequirementRule.objects.create(corso=spenta, legacy_anagrafica_id=902, is_active=False)
        res = self.calcola("personale_formazione")
        self.assertEqual([(r["codice"], r["origine"]) for r in res.righe], [("C-RUOLO", "Ruolo «Preposto»")])

    def test_ruolo_concluso_non_genera_obblighi(self):
        corso = self.corso("C-EX")
        ruolo = RuoloOperativo.objects.create(nome="Ex addetto")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=902, ruolo=ruolo,
                                                data_fine=OGGI - timedelta(days=5))
        TrainingRequirementRule.objects.create(corso=corso, ruolo_operativo=ruolo)
        self.assertEqual(self.calcola("personale_formazione").righe, [])

    def test_matrice_usa_lo_stesso_calcolo(self):
        corso = self.corso("C-M")
        TrainingRequirementRule.objects.create(corso=corso, legacy_anagrafica_id=902)
        self.completamento(902, corso, 10, scadenza=OGGI + timedelta(days=10))
        res = self.calcola("matrice_formazione")
        riga = next(r for r in res.righe if r["nominativo"] == "BIANCHI LUCA")
        self.assertEqual(riga[f"c{corso.pk}"], "!")


class VisiteTest(_Base):
    def setUp(self):
        super().setUp()
        self.annuale = TipoVisitaMedica.objects.create(nome="Visita medica annuale", durata_mesi=12,
                                                       categoria="Visita medica")
        self.biennale = TipoVisitaMedica.objects.create(nome="Visita medica biennale", durata_mesi=24,
                                                        categoria="Visita medica")
        self.ruolo = RuoloOperativo.objects.create(nome="Saldatore")
        self.biennale.ruoli_operativi.add(self.ruolo)

    def _sorveglianza(self, **o):
        with patch("anagrafica.reportistica.sezioni.has_perm", return_value=True):
            return self.calcola("sicurezza_sorveglianza", **o)

    def test_cambio_periodicita_non_lascia_la_vecchia_scaduta(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=901, ruolo=self.ruolo)
        VisitaMedica.objects.create(legacy_anagrafica_id=901, tipo=self.annuale,
                                    data_svolgimento=OGGI - timedelta(days=500))
        VisitaMedica.objects.create(legacy_anagrafica_id=951, tipo=self.biennale,
                                    data_svolgimento=OGGI - timedelta(days=30))
        res = self._sorveglianza()
        self.assertEqual([(r["nominativo"], r["visita"], r["stato"]) for r in res.righe],
                         [("ROSSI ANNA", "Visita medica biennale", "Valida")])

    def test_chi_non_e_soggetto_non_risulta_mancante(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=902, ruolo=self.ruolo)
        res = self._sorveglianza()
        self.assertEqual([(r["nominativo"], r["stato"]) for r in res.righe],
                         [("BIANCHI LUCA", "Dovuta, mai registrata")])
        kpi = {k.label: k.value for k in res.kpis}
        self.assertEqual(kpi["Persone soggette a sorveglianza"], 1)
        self.assertEqual(kpi["Visite dovute mai registrate"], 1)

    def test_visita_superata_non_restituisce_la_precedente(self):
        VisitaMedica.objects.create(legacy_anagrafica_id=902, tipo=self.annuale,
                                    data_svolgimento=OGGI - timedelta(days=800))
        VisitaMedica.objects.create(legacy_anagrafica_id=902, tipo=self.annuale,
                                    data_svolgimento=OGGI - timedelta(days=100), superata_il=timezone.now())
        res = self._sorveglianza()
        self.assertEqual(res.righe, [])


class NienteDatiPersiInSilenzioTest(_Base):
    def test_qualifiche_escluse_spiegate_nel_documento(self):
        tipo = TipoQualifica.objects.create(nome="Primo soccorso")
        DipendenteQualifica.objects.create(legacy_anagrafica_id=903, tipo=tipo)  # cessato
        DipendenteQualifica.objects.create(legacy_anagrafica_id=7777, tipo=tipo)  # anagrafica inesistente
        modello = ReportModello.objects.create(nome="Q", titolo_documento="Q", mostra_note_calcolo=False)
        ReportBlocco.objects.create(modello=modello, ordine=10, tipo="SEZIONE", sezione="personale_qualifiche")
        doc = motore.componi(modello, motore.Parametri.dal_modello(modello), None)
        note = " ".join(doc.sezioni_calcolate[0].note)
        self.assertIn("Qualifiche di persone non più in forza, non riportate: 1.", note)
        self.assertIn("Qualifiche agganciate a un'anagrafica che non esiste più: 1.", note)

    def test_filtro_in_a_blocchi_oltre_il_limite_di_sql_server(self):
        self.assertEqual([len(b) for b in a_blocchi(range(2500))], [1000, 1000, 500])
        tipo = TipoQualifica.objects.create(nome="Q blocchi")
        DipendenteQualifica.objects.create(legacy_anagrafica_id=2400, tipo=tipo)
        trovate = filtra_in(DipendenteQualifica.objects.all(), "legacy_anagrafica_id", range(1, 2600))
        self.assertEqual([q.legacy_anagrafica_id for q in trovate], [2400])


class CalcoliCondivisiTest(_Base):
    def test_corso_dismesso_mai_frequentato_non_e_un_obbligo(self):
        corso = self.corso("C-OLD", attivo=False)
        TrainingRequirementRule.objects.create(corso=corso, legacy_anagrafica_id=902)
        ctx = self.ctx()
        voci = calcoli.formazione(ctx, {p.id: p for p in ctx.dipendenti()})
        self.assertEqual(voci, [])

    def test_report_conformita_competenze_allineato(self):
        from report_conformita.registry import ReportParams, get_report

        corso = self.corso("C-RC")
        TrainingRequirementRule.objects.create(corso=corso, legacy_anagrafica_id=902)
        TrainingDeadline.objects.create(corso=corso, legacy_anagrafica_id=902, stato_scadenza="VALIDO",
                                        is_required=True)
        result = get_report("competenze").build(ReportParams(date_from=OGGI - timedelta(days=365),
                                                             date_to=OGGI, today=OGGI))
        self.assertEqual([r[3] for r in result.rows], ["Corso C-RC"])
        self.assertEqual([r[5] for r in result.rows], ["Mai frequentato"])
