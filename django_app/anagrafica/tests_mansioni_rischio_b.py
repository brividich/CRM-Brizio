"""Mansioni di rischio ≠ mansioni lavorative: motore, override, cambio mansione a prova
di errore, stato operativo, migrazione dati, integrità.

Dati **sintetici**: anagrafiche legacy create nel DB di test, nessun dato reale.
Ogni classe copre una riga della tabella dei casi del prompt 04.
"""
from __future__ import annotations

import io
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import (
    AdempimentoCambioMansione as A, ConfigSicurezzaOperativa, DipendenteAnagraficaAziendale,
    DipendenteAssegnazione, DipendenteMansioneRischioOverride as O, EsposizioneRischio,
    EventoSicurezzaDipendente, FattoreRischio, Mansione, MansioneLavorativaRischio, MansioneRischio,
    TipoVisitaMedica, TrainingCourse, TrainingPlan, TrainingRequirementRule, VisitaMedica,
)
from anagrafica.services import cambio_mansione, mansionario, riallineamento, stato_operativo
from anagrafica.services.assegnazioni import crea_assegnazione
from core.legacy_models import AnagraficaDipendente

User = get_user_model()
OGGI = timezone.localdate()


class _Base(TestCase):
    """Operaio (rumore → audiometria) che può diventare saldatore (fumi → visita annuale)."""

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("mr_admin_test", "mr@example.invalid", "x")
        self.audiometria = TipoVisitaMedica.objects.create(nome="Audiometria sintetica", durata_mesi=24,
                                                           categoria="Audiometria")
        self.annuale = TipoVisitaMedica.objects.create(nome="Visita annuale sintetica", durata_mesi=12,
                                                       categoria="Visita generale")
        self.oculistica = TipoVisitaMedica.objects.create(nome="Visita oculistica sintetica", durata_mesi=24,
                                                          categoria="Oculistica")
        self.rumore = FattoreRischio.objects.create(codice="RUM-T", nome="Rumore", richiede_visita_medica=True)
        self.rumore.tipi_visita.add(self.audiometria)
        self.fumi = FattoreRischio.objects.create(codice="FUM-T", nome="Fumi", richiede_visita_medica=True)
        self.fumi.tipi_visita.add(self.annuale)

        self.mr_rumore = MansioneRischio.objects.create(codice="MR-RUM", nome="Esposti rumore")
        self.mr_rumore.fattori.add(self.rumore)
        self.mr_fumi = MansioneRischio.objects.create(codice="MR-FUM", nome="Esposti fumi")
        self.mr_fumi.fattori.add(self.fumi)

        self.operaio = Mansione.objects.create(nome="Operaio T")
        self.saldatore = Mansione.objects.create(nome="Saldatore T")
        MansioneLavorativaRischio.objects.create(mansione=self.operaio, mansione_rischio=self.mr_rumore)
        MansioneLavorativaRischio.objects.create(mansione=self.saldatore, mansione_rischio=self.mr_fumi)

        self.lid = self._dipendente("Mario", "Rossi", "Operaio T")

    def _dipendente(self, nome, cognome, mansione):
        dip = AnagraficaDipendente.objects.create(nome=nome, cognome=cognome, mansione=mansione,
                                                  reparto="Produzione", aliasusername=f"{nome}.{cognome}.t".lower())
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=dip.id,
                                                     data_assunzione_ultima=OGGI - timedelta(days=900))
        return dip.id

    def _card(self, legacy_id, mansione, giorni=-100):
        return DipendenteAssegnazione.objects.create(
            legacy_anagrafica_id=legacy_id, data_inizio=OGGI + timedelta(days=giorni), mansione=mansione,
            reparto="Produzione", attivata_il=timezone.now(),
        )


# ── Motore: mansioni di rischio, provenienza, override ────────────────────────
class MotoreMansioniRischioTests(_Base):
    def test_requisiti_dalla_mansione_di_rischio_con_provenienza(self):
        det = mansionario.requisiti_dipendente_dettaglio(self.lid)
        self.assertEqual([v.pk for v in det["requisiti"]["visite"]], [self.audiometria.pk])
        self.assertEqual(det["origini"][("visite", self.audiometria.pk)],
                         ["Mansione di rischio «Esposti rumore» (da mansione «Operaio T»)"])
        self.assertEqual(det["origini_strutturate"][("visite", self.audiometria.pk)]["mansione_rischio_id"],
                         self.mr_rumore.pk)

    def test_campi_legacy_ignorati_se_la_mansione_ha_collegamenti(self):
        self.operaio.visite_richieste.add(self.oculistica)
        visite = {v.pk for v in mansionario.requisiti_mansione(self.operaio)["visite"]}
        self.assertEqual(visite, {self.audiometria.pk})

    def test_mansione_senza_collegamenti_legge_i_campi_legacy(self):
        magazziniere = Mansione.objects.create(nome="Magazziniere T")
        magazziniere.visite_richieste.add(self.oculistica)
        EsposizioneRischio.objects.create(fattore=self.rumore, mansione=magazziniere)
        visite = {v.pk for v in mansionario.requisiti_mansione(magazziniere)["visite"]}
        self.assertEqual(visite, {self.oculistica.pk, self.audiometria.pk})

    def test_override_aggiunta_ed_esclusione(self):
        O.objects.create(legacy_anagrafica_id=self.lid, mansione_rischio=self.mr_fumi, azione=O.AZIONE_AGGIUNGI,
                         motivo="Addetto saldature occasionali", data_inizio=OGGI)
        O.objects.create(legacy_anagrafica_id=self.lid, mansione_rischio=self.mr_rumore, azione=O.AZIONE_ESCLUDI,
                         motivo="Postazione insonorizzata (DVR rev. 3)", data_inizio=OGGI)
        det = mansionario.requisiti_dipendente_dettaglio(self.lid)
        self.assertEqual({v.pk for v in det["requisiti"]["visite"]}, {self.annuale.pk})
        self.assertIn("aggiunta individuale", det["origini"][("visite", self.annuale.pk)][0])
        self.assertEqual([e["mansione_rischio"].pk for e in det["mansioni_rischio_escluse"]], [self.mr_rumore.pk])

    def test_override_futuro_o_revocato_non_vale(self):
        O.objects.create(legacy_anagrafica_id=self.lid, mansione_rischio=self.mr_fumi, azione=O.AZIONE_AGGIUNGI,
                         motivo="Dal mese prossimo", data_inizio=OGGI + timedelta(days=30))
        self.assertNotIn(self.annuale, mansionario.requisiti_dipendente(self.lid)["visite"])
        self.assertIn(self.annuale, mansionario.requisiti_dipendente(self.lid, data=OGGI + timedelta(days=31))["visite"])

    def test_motivo_override_obbligatorio(self):
        with self.assertRaises(ValidationError):
            riallineamento.aggiungi_override(self.lid, self.mr_fumi, azione=O.AZIONE_AGGIUNGI, motivo=" ",
                                             data_inizio=OGGI, user=self.admin)

    def test_regola_formativa_su_mansione_di_rischio(self):
        piano, _ = TrainingPlan.objects.get_or_create(codice="PT-MR", defaults={"nome": "P", "stato": "ATTIVO"})
        corso = TrainingCourse.objects.create(piano=piano, codice="RUM-C", titolo="Rischio rumore",
                                              durata_ore_teorica=2, validita_mesi=60)
        TrainingRequirementRule.objects.create(corso=corso, mansione_rischio=self.mr_rumore)
        self.assertIn(corso, mansionario.requisiti_dipendente(self.lid)["corsi"])


# ── Override: delta sugli adempimenti ─────────────────────────────────────────
class OverrideRiallineamentoTests(_Base):
    def test_aggiunta_crea_adempimento_e_revoca_lo_chiude(self):
        card = self._card(self.lid, "Operaio T")
        override, esito = riallineamento.aggiungi_override(
            self.lid, self.mr_fumi, azione=O.AZIONE_AGGIUNGI, motivo="Addetto saldature", data_inizio=OGGI,
            user=self.admin)
        self.assertEqual(esito["creati"], 1)
        ad = card.adempimenti.get(chiave=f"VISITA:{self.annuale.pk}")
        self.assertEqual((ad.origine_tipo, ad.origine_override_id), ("OVERRIDE", override.pk))

        riallineamento.revoca_override(override, motivo="Fine incarico", user=self.admin)
        ad.refresh_from_db()
        self.assertEqual((ad.stato, ad.attivo), (A.STATO_NON_PIU_DOVUTO, False))
        override.refresh_from_db()
        self.assertFalse(override.attivo)  # revocato, non cancellato
        tipi = set(EventoSicurezzaDipendente.objects.filter(legacy_anagrafica_id=self.lid).values_list("tipo", flat=True))
        self.assertTrue({"OVERRIDE_AGGIUNTO", "OVERRIDE_REVOCATO", "PIANO_AGGIORNATO"} <= tipi)


# ── Cambio mansione ───────────────────────────────────────────────────────────
class CambioMansioneTests(_Base):
    def test_cambio_semplice_con_rischi_in_piu_e_in_meno(self):
        c = cambio_mansione.confronta(self.lid, "Saldatore T")
        self.assertEqual([f.pk for f in c.rischi_acquisiti], [self.fumi.pk])
        self.assertEqual([f.pk for f in c.rischi_persi], [self.rumore.pk])
        ass = crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=15), mansione="Saldatore T",
                                user=self.admin)
        visite = ass.adempimenti.filter(tipo="VISITA")
        self.assertEqual([a.chiave for a in visite], [f"VISITA:{self.annuale.pk}"])
        self.assertEqual(visite[0].origine_tipo, "MANSIONE_RISCHIO")
        self.assertEqual(visite[0].origine_mansione_rischio_id, self.mr_fumi.pk)

    def test_doppia_esecuzione_idempotente(self):
        ass = crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=15), mansione="Saldatore T",
                                user=self.admin)
        prima = sorted(ass.adempimenti.values_list("pk", "chiave"))
        for _ in range(2):
            cambio_mansione.genera_piano(ass, mansione_precedente="Operaio T", user=self.admin)
        self.assertEqual(sorted(ass.adempimenti.values_list("pk", "chiave")), prima)

    def test_rigenerazione_chiude_come_non_piu_dovuto(self):
        ass = crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=15), mansione="Saldatore T",
                                user=self.admin)
        self.mr_fumi.fattori.remove(self.fumi)
        cambio_mansione.genera_piano(ass, mansione_precedente="Operaio T", user=self.admin)
        ad = A.objects.get(assegnazione=ass, chiave=f"VISITA:{self.annuale.pk}")
        self.assertEqual((ad.stato, ad.attivo), (A.STATO_NON_PIU_DOVUTO, False))

    def test_programmato_poi_annullato(self):
        self.client.force_login(self.admin)
        ass = crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=20), mansione="Saldatore T",
                                user=self.admin)
        ids = list(ass.adempimenti.values_list("pk", flat=True))
        self.assertTrue(ids)
        r = self.client.post(reverse("anagrafica:dipendente_assegnazione_annulla", args=[self.lid, ass.pk]),
                             {"motivo": "Data sbagliata"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(DipendenteAssegnazione.objects.filter(pk=ass.pk).exists())
        for ad in A.objects.filter(pk__in=ids):  # annullati, non cancellati
            self.assertEqual((ad.stato, ad.attivo, ad.assegnazione_id), (A.STATO_ANNULLATO, False, None))
            self.assertIn("Data sbagliata", ad.annullato_motivo)
        self.assertTrue(EventoSicurezzaDipendente.objects.filter(
            legacy_anagrafica_id=self.lid, tipo="ASSEGNAZIONE_ANNULLATA").exists())

    def test_spostamenti_programmati_in_fila_usano_la_card_precedente(self):
        crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=10), mansione="Saldatore T", user=self.admin)
        terza = Mansione.objects.create(nome="Saldatore capo T")
        MansioneLavorativaRischio.objects.create(mansione=terza, mansione_rischio=self.mr_fumi)
        ass2 = crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=40), mansione="Saldatore capo T",
                                 user=self.admin)
        # Baseline = Saldatore (programmato), non Operaio: niente visita «nuova» da rifare.
        self.assertFalse(ass2.adempimenti.filter(tipo="VISITA").exists())

    def test_cambio_retroattivo_e_stato_operativo(self):
        ass = crea_assegnazione(self.lid, data_inizio=OGGI - timedelta(days=5), mansione="Saldatore T",
                                user=self.admin)
        self.assertEqual(ass.adempimenti.get(tipo="VISITA").entro_il, OGGI - timedelta(days=5))
        stato = stato_operativo.stato_persona([self.lid])
        self.assertEqual(stato.codice, stato_operativo.AVVISO)  # default: solo avviso
        self.assertFalse(stato.bloccante)

    def test_visita_del_tipo_sbagliato_non_chiude(self):
        ass = crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=5), mansione="Saldatore T",
                                user=self.admin)
        VisitaMedica.objects.create(legacy_anagrafica_id=self.lid, tipo=self.oculistica, data_svolgimento=OGGI)
        cambio_mansione.aggiorna_piani([self.lid])
        self.assertEqual(ass.adempimenti.get(tipo="VISITA").stato, A.STATO_APERTO)
        VisitaMedica.objects.create(legacy_anagrafica_id=self.lid, tipo=self.annuale, data_svolgimento=OGGI)
        cambio_mansione.aggiorna_piani([self.lid])
        self.assertEqual(ass.adempimenti.get(tipo="VISITA").stato, A.STATO_COMPLETATO)


# ── Stato operativo: non idoneità, deroghe, privacy ──────────────────────────
class StatoOperativoTests(_Base):
    def _visita_mancante(self):
        crea_assegnazione(self.lid, data_inizio=OGGI - timedelta(days=1), mansione="Saldatore T", user=self.admin)

    def _modalita(self, valore):
        cfg = ConfigSicurezzaOperativa.load()
        cfg.modalita_visita_mancante = valore
        cfg.save()

    def test_non_idoneita_blocca_sempre(self):
        VisitaMedica.objects.create(legacy_anagrafica_id=self.lid, tipo=self.audiometria,
                                    data_svolgimento=OGGI, esito="NON_IDONEO_TEMP")
        stato = stato_operativo.stato_persona([self.lid])
        self.assertTrue(stato.bloccante)
        self.assertEqual(stato.etichetta, "Non idoneo a operare")

    def test_modalita_deroga(self):
        self._modalita(ConfigSicurezzaOperativa.MODALITA_DEROGA)
        self._visita_mancante()
        self.assertEqual(stato_operativo.stato_persona([self.lid]).etichetta, "Non idoneo a operare: visita mancante")
        stato_operativo.concedi_deroga(self.lid, motivo="Visita prenotata il 20, mansione affiancata",
                                       valida_fino=OGGI + timedelta(days=10), user=self.admin)
        self.assertEqual(stato_operativo.stato_persona([self.lid]).codice, stato_operativo.DEROGA)
        with self.assertRaises(ValidationError):
            stato_operativo.concedi_deroga(self.lid, motivo="troppo lunga", valida_fino=OGGI + timedelta(days=90),
                                           user=self.admin)

    def test_blocco_ignora_le_deroghe(self):
        self._modalita(ConfigSicurezzaOperativa.MODALITA_BLOCCO)
        self._visita_mancante()
        with self.assertRaises(ValidationError):
            stato_operativo.concedi_deroga(self.lid, motivo="x", valida_fino=OGGI, user=self.admin)
        self.assertTrue(stato_operativo.stato_persona([self.lid]).bloccante)

    def test_motivi_nascosti_senza_permesso_sanitario(self):
        VisitaMedica.objects.create(legacy_anagrafica_id=self.lid, tipo=self.audiometria,
                                    data_svolgimento=OGGI, esito="NON_IDONEO_DEF")
        stato = stato_operativo.stato_persona([self.lid])
        self.assertEqual(stato.motivi_visibili(False), [])
        self.assertTrue(stato.motivi_visibili(True))


# ── Modifica admin del collegamento: job su 50 dipendenti ────────────────────
class RiallineamentoMassivoTests(_Base):
    def test_cinquanta_dipendenti_idempotente(self):
        ids = [self._dipendente(f"Nome{i}", f"Sintetico{i}", "Operaio T") for i in range(50)]
        for lid in ids:
            self._card(lid, "Operaio T")
        foto = riallineamento.fotografa_mansioni([self.operaio.pk])
        MansioneLavorativaRischio.objects.create(mansione=self.operaio, mansione_rischio=self.mr_fumi, ordine=1)
        report = riallineamento.esegui_riallineamento({str(k): v for k, v in foto.items()}, "Test collegamento")
        self.assertEqual(report["dipendenti"], 51)  # i 50 + il dipendente dello scenario
        self.assertEqual(report["creati"], 50)       # lo scenario non ha card aperta
        self.assertEqual(report["senza_assegnazione"], 1)
        again = riallineamento.esegui_riallineamento({str(k): v for k, v in foto.items()}, "Test collegamento")
        self.assertEqual(again["creati"], 0)
        self.assertEqual(A.objects.filter(legacy_anagrafica_id__in=ids, chiave=f"VISITA:{self.annuale.pk}").count(), 50)


# ── Migrazione dati ───────────────────────────────────────────────────────────
class MigrazioneDatiTests(TestCase):
    def setUp(self):
        self.visita = TipoVisitaMedica.objects.create(nome="Visita sintetica M", durata_mesi=12)
        self.fattore = FattoreRischio.objects.create(codice="MIG-F", nome="Fattore M")
        self.verniciatore = Mansione.objects.create(nome="Verniciatore M")
        self.verniciatore.visite_richieste.add(self.visita)
        EsposizioneRischio.objects.create(fattore=self.fattore, mansione=self.verniciatore)
        self.impiegato = Mansione.objects.create(nome="Impiegato M")  # profilo vuoto
        self.dubbia = Mansione.objects.create(nome="Dubbia M")
        EsposizioneRischio.objects.create(fattore=self.fattore, mansione=self.dubbia, note="solo turno notte")

    def _cmd(self, *args):
        out = io.StringIO()
        call_command("migra_mansioni_rischio", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_non_scrive(self):
        out = self._cmd()
        self.assertIn("[MAPPATO]", out)
        self.assertIn("[SKIP_VUOTO]", out)
        self.assertIn("[DA_DECIDERE]", out)
        self.assertFalse(MansioneRischio.objects.exists())

    def test_apply_idempotente_equivalente_e_rollback(self):
        prima = {d: {o.pk for o in v} for d, v in mansionario.requisiti_mansione(self.verniciatore).items()}
        self._cmd("--apply")
        mr = MansioneRischio.objects.get(origine_mansione=self.verniciatore)
        self.assertEqual(mr.codice, f"MR-{self.verniciatore.pk:04d}")
        self.assertTrue(MansioneLavorativaRischio.objects.filter(mansione=self.verniciatore, mansione_rischio=mr).exists())
        self.assertFalse(MansioneRischio.objects.filter(origine_mansione=self.dubbia).exists())  # da decidere
        dopo = {d: {o.pk for o in v} for d, v in mansionario.requisiti_mansione(self.verniciatore).items()}
        self.assertEqual(prima, dopo)
        self.assertIn("0 differenze", self._cmd("--verifica"))

        self.assertIn("[GIA_MIGRATO]", self._cmd("--apply"))
        self.assertEqual(MansioneRischio.objects.count(), 1)

        self.assertIn("[DA_RIMUOVERE]", self._cmd("--rollback"))  # dry-run
        self.assertTrue(MansioneRischio.objects.exists())
        self._cmd("--rollback", "--apply")
        self.assertFalse(MansioneRischio.objects.exists())
        self.assertEqual(list(self.verniciatore.visite_richieste.all()), [self.visita])  # legacy intatto

    def test_rollback_rifiutato_se_modificata(self):
        self._cmd("--apply")
        mr = MansioneRischio.objects.get(origine_mansione=self.verniciatore)
        mr.visite.clear()
        self.assertIn("[NON_ROLLBACKABILE]", self._cmd("--rollback", "--apply"))
        self.assertTrue(MansioneRischio.objects.filter(pk=mr.pk).exists())

    def test_divergente_dopo_modifica_del_legacy(self):
        self._cmd("--apply")
        self.verniciatore.visite_richieste.clear()
        self.assertIn("[DIVERGENTE]", self._cmd("--apply"))

    def test_nome_mansione_dipendente_non_a_catalogo(self):
        AnagraficaDipendente.objects.create(nome="A", cognome="B", mansione="Mansione Fantasma",
                                            reparto="X", aliasusername="ab.mig.t")
        self.assertIn("[NON_MAPPATO_DIPENDENTE]", self._cmd())


class MigrazioneBackfillChiaveTests(TestCase):
    def test_backfill_tiene_la_piu_recente(self):
        import importlib
        from django.apps import apps
        mod = importlib.import_module("anagrafica.migrations.0140_adempimento_chiave_backfill")
        ass = DipendenteAssegnazione.objects.create(legacy_anagrafica_id=1, data_inizio=OGGI, mansione="X")
        vecchio = A.objects.create(assegnazione=ass, legacy_anagrafica_id=1, tipo="VISITA", riferimento_id=5,
                                   descrizione="Visita: nome vecchio", entro_il=OGGI, chiave="tmp1")
        nuovo = A.objects.create(assegnazione=ass, legacy_anagrafica_id=1, tipo="VISITA", riferimento_id=5,
                                 descrizione="Visita: nome nuovo", entro_il=OGGI, chiave="tmp2")
        A.objects.filter(pk=nuovo.pk).update(created_at=timezone.now() + timedelta(seconds=5))
        mod.avanti(apps, None)
        vecchio.refresh_from_db(), nuovo.refresh_from_db()
        self.assertEqual((nuovo.chiave, nuovo.attivo), ("VISITA:5", True))
        self.assertEqual((vecchio.chiave, vecchio.attivo, vecchio.stato), ("VISITA:5", False, A.STATO_NON_PIU_DOVUTO))
        mod.indietro(apps, None)  # nessun orfano: no-op

    def test_reverse_si_ferma_con_gli_orfani(self):
        import importlib
        from django.apps import apps
        mod = importlib.import_module("anagrafica.migrations.0140_adempimento_chiave_backfill")
        A.objects.create(assegnazione=None, legacy_anagrafica_id=1, tipo="VISITA", descrizione="x",
                         entro_il=OGGI, chiave="VISITA:0", attivo=False, stato=A.STATO_ANNULLATO)
        with self.assertRaises(RuntimeError):
            mod.indietro(apps, None)


# ── Integrità notturna e notifiche ───────────────────────────────────────────
class IntegritaENotificheTests(_Base):
    def test_integrita_segnala_e_pubblica_in_monitoring(self):
        from anagrafica.services.integrita_scadenze import pubblica_in_monitoring, verifica
        from monitoring.models import Issue

        VisitaMedica.objects.create(legacy_anagrafica_id=self.lid, tipo=self.audiometria,
                                    data_svolgimento=OGGI, esito="NON_IDONEO_TEMP")
        sezioni = {s.titolo: s for s in verifica(aree=("sicurezza",))}
        righe = sezioni["Persone non idonee a operare"].righe
        self.assertEqual(len(righe), 1)
        self.assertNotIn("Audiometria", righe[0])  # niente dati sanitari nel report
        esito = pubblica_in_monitoring(list(sezioni.values()))
        self.assertEqual(esito["errori"], 1)
        self.assertTrue(Issue.objects.filter(module_name="anagrafica").exists())

    def test_notifica_dopo_il_commit_senza_dati_clinici(self):
        from django.core import mail
        from core.models import SiteConfig

        SiteConfig.set("cambio_mansione_emails", "rspp@example.invalid")
        with self.captureOnCommitCallbacks(execute=True):
            crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=15), mansione="Saldatore T", user=self.admin)
        self.assertEqual(len(mail.outbox), 1)
        corpo = mail.outbox[0].body
        self.assertIn("Visita medica", corpo)
        self.assertNotIn("annuale sintetica", corpo)

    def test_senza_destinatari_nessuna_mail(self):
        from django.core import mail
        with self.captureOnCommitCallbacks(execute=True):
            crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=15), mansione="Saldatore T", user=self.admin)
        self.assertEqual(len(mail.outbox), 0)


# ── A8: referti serviti e caricati in modo sicuro ────────────────────────────
class RefertiDownloadSicuroTests(TestCase):
    PDF = b"%PDF-1.4\n%sintetico\n"
    HTML = b"<html><script>alert(1)</script></html>"
    SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"

    def setUp(self):
        self.admin = User.objects.create_superuser("a8_admin_test", "a8@example.invalid", "x")
        self.client.force_login(self.admin)

    def _doc(self, nome, contenuto, radice):
        from django.core.files.base import ContentFile
        from anagrafica.models import DocumentoDipendente
        with self.settings(ANAGRAFICA_PRIVATE_ROOT=radice):
            doc = DocumentoDipendente(legacy_anagrafica_id=1, tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
                                      nome_originale=nome, tipo_mime="text/html")
            doc.file.save(nome, ContentFile(contenuto), save=True)
        return doc

    def _scarica(self, nome, contenuto):
        import tempfile
        with tempfile.TemporaryDirectory() as radice:
            doc = self._doc(nome, contenuto, radice)
            with self.settings(ANAGRAFICA_PRIVATE_ROOT=radice):
                r = self.client.get(reverse("anagrafica:documento_download", args=[doc.pk]))
                b"".join(r.streaming_content)
                # Non r.close(): emette request_finished e chiude la connessione DB del test.
                for chiudibile in getattr(r, "_resource_closers", []):
                    chiudibile()
            return r

    def test_html_e_svg_serviti_come_allegato_con_sandbox(self):
        for nome, contenuto in (("referto.html", self.HTML), ("referto.svg", self.SVG),
                                ("finto.pdf", self.HTML)):  # .pdf che contiene HTML
            r = self._scarica(nome, contenuto)
            self.assertEqual(r["Content-Type"], "application/octet-stream", nome)
            self.assertTrue(r["Content-Disposition"].startswith("attachment"), nome)
            self.assertIn("sandbox", r["Content-Security-Policy"], nome)

    def test_pdf_vero_resta_inline(self):
        r = self._scarica("referto.pdf", self.PDF)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r["Content-Disposition"].startswith("inline"))

    def test_upload_referto_non_pdf_rifiutato(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from anagrafica.forms import VisitaMedicaForm
        tipo = TipoVisitaMedica.objects.create(nome="Tipo A8", durata_mesi=12)
        form = VisitaMedicaForm(
            {"tipo": tipo.pk, "data_svolgimento": OGGI.isoformat(), "esito": "IDONEO"},
            {"referto_file": SimpleUploadedFile("referto.html", self.HTML, content_type="application/pdf")},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("referto_file", form.errors)

    def test_caricamento_referti_scarta_html_prima_di_archiviare(self):
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        with mock.patch("anagrafica.services.referti_intake.elabora_documenti", return_value=[]) as elabora:
            self.client.post(reverse("anagrafica:referti_carica"),
                             {"referti": [SimpleUploadedFile("x.html", self.HTML, content_type="application/pdf")]})
        self.assertEqual(elabora.call_args[0][0], [])  # nessun documento passato all'archivio
