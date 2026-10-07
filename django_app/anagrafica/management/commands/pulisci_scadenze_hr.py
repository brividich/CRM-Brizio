"""Pulizia guidata dei dati di scadenza trovati da ``verifica_scadenze_hr``.

Uso:
    python manage.py pulisci_scadenze_hr                       # anteprima di tutto
    python manage.py pulisci_scadenze_hr --doppioni --applica  # elimina gli attestati doppi
    python manage.py pulisci_scadenze_hr --validita-corsi --applica

Senza ``--applica`` non scrive nulla. Con ``--applica`` lavora in una
transazione, registra ogni modifica in AuditLog e ricalcola le scadenze delle
persone toccate.

- ``--doppioni``: stesso attestato (persona, corso, data) registrato piu' volte.
  Si tiene quello con iscrizione, attestato, protocollo o documento; si eliminano
  solo le copie senza nulla di collegato e con ore non superiori; le altre vanno
  viste a mano.
- ``--validita-corsi``: corsi a validita' 0 («una tantum») i cui attestati hanno
  una scadenza. Si imposta la validita' piu' frequente fra gli attestati, solo se
  vale per almeno l'80% di essi.

Date future e persone inesistenti non hanno una correzione deducibile: restano
nel rapporto di ``verifica_scadenze_hr`` e vanno sistemate a mano.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

QUOTA_MINIMA = 0.8


class _Anteprima(Exception):
    pass


class Command(BaseCommand):
    help = "Elimina attestati doppi e allinea la validita' dei corsi (anteprima se manca --applica)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--doppioni", action="store_true", help="Attestati doppi (persona, corso, data).")
        parser.add_argument("--validita-corsi", action="store_true",
                            help="Validita' dei corsi una tantum con attestati che scadono.")
        parser.add_argument("--applica", action="store_true", help="Scrive le modifiche (default: anteprima).")

    def handle(self, *args, **options) -> None:
        tutti = not (options["doppioni"] or options["validita_corsi"])
        applica = options["applica"]
        self.persone: set[int] = set()
        try:
            with transaction.atomic():
                if tutti or options["doppioni"]:
                    self._doppioni()
                if tutti or options["validita_corsi"]:
                    self._validita_corsi()
                if not applica:
                    raise _Anteprima
                if self.persone:
                    from anagrafica.services.scadenze import ricalcola_tutto

                    ricalcola_tutto(sorted(self.persone))
        except _Anteprima:
            self.stdout.write(self.style.WARNING("\nAnteprima: nessuna modifica salvata (usa --applica)."))
            return
        self.stdout.write(self.style.SUCCESS(f"\nModifiche salvate; scadenze ricalcolate per {len(self.persone)} persone."))

    def _audit(self, azione: str, oggetto_tipo: str, oggetto_id, dettaglio: dict) -> None:
        from core.models import AuditLog

        AuditLog.objects.create(utente_display="manage.py pulisci_scadenze_hr", azione=azione,
                                modulo="formazione", oggetto_tipo=oggetto_tipo,
                                oggetto_id=str(oggetto_id), dettaglio=dettaglio)

    # ── Attestati doppi ───────────────────────────────────────────────────
    def _collegamenti(self, r) -> list[str]:
        from anagrafica.models import DipendenteQualifica, DocumentoDipendente
        from anagrafica.models_formazione import (
            TrainingCertificate, TrainingEfficacia, TrainingElearningEnrollment, TrainingQuizAttempt,
        )

        motivi = []
        if r.enrollment_id:
            motivi.append("iscrizione")
        if r.numero_protocollo:
            motivi.append(f"protocollo {r.numero_protocollo}")
        if TrainingCertificate.objects.filter(record=r).exists():
            motivi.append("attestato")
        if DocumentoDipendente.objects.filter(tipo=DocumentoDipendente.Tipo.CERTIFICATO_FORMAZIONE,
                                              oggetto_riferimento_id=r.pk).exists():
            motivi.append("documento")
        if TrainingEfficacia.objects.filter(record=r).exists():
            motivi.append("valutazione efficacia")
        if TrainingQuizAttempt.objects.filter(record=r).exists():
            motivi.append("quiz")
        if TrainingElearningEnrollment.objects.filter(record_completamento=r).exists():
            motivi.append("e-learning")
        if DipendenteQualifica.objects.filter(record_formazione=r).exists():
            motivi.append("qualifica")
        return motivi

    def _doppioni(self) -> None:
        from anagrafica.models_formazione import TrainingEmployeeRecord

        gruppi = defaultdict(list)
        for r in TrainingEmployeeRecord.objects.select_related("corso").order_by("pk"):
            gruppi[(r.legacy_anagrafica_id, r.corso_id, r.data_completamento)].append(r)
        gruppi = {k: v for k, v in gruppi.items() if len(v) > 1}
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n== Attestati doppi: {len(gruppi)} gruppi =="))
        eliminati = a_mano = 0
        for (lid, _corso, data), recs in gruppi.items():
            info = [(r, self._collegamenti(r)) for r in recs]
            # Si tiene il piu' «collegato»; a parita' il primo inserito.
            tieni = max(info, key=lambda x: (len(x[1]), -x[0].pk))[0]
            for r, motivi in info:
                if r is tieni:
                    continue
                desc = (f"persona {lid} corso {r.corso.codice} del {data:%d/%m/%Y}: "
                        f"#{r.pk} ({r.ore_frequentate} h) doppione di #{tieni.pk} ({tieni.ore_frequentate} h)")
                if not motivi and (r.ore_frequentate or 0) > (tieni.ore_frequentate or 0):
                    # La copia dice di piu' (ore): forse e' l'altra quella giusta.
                    motivi = ["piu' ore di quello da tenere"]
                if motivi:
                    a_mano += 1
                    self.stdout.write(self.style.WARNING(f"  da vedere a mano: {desc} — ha {', '.join(motivi)}"))
                    continue
                eliminati += 1
                self.stdout.write(f"  elimina {desc}")
                self._audit("formazione_attestato_doppio_eliminato", "anagrafica.trainingemployeerecord", r.pk, {
                    "tenuto": tieni.pk, "legacy_anagrafica_id": lid, "corso": r.corso.codice,
                    "data_completamento": data.isoformat(), "ore": str(r.ore_frequentate),
                })
                r.delete()
                self.persone.add(lid)
        self.stdout.write(f"  totale: {eliminati} da eliminare, {a_mano} da vedere a mano")

    # ── Validita' dei corsi una tantum ────────────────────────────────────
    def _validita_corsi(self) -> None:
        from anagrafica.models_formazione import TrainingCourse, TrainingEmployeeRecord

        per_corso = defaultdict(list)
        for lid, corso_id, fatto, scade in TrainingEmployeeRecord.objects.filter(
                corso__validita_mesi=0, data_scadenza__isnull=False).values_list(
                "legacy_anagrafica_id", "corso_id", "data_completamento", "data_scadenza"):
            per_corso[corso_id].append((lid, round((scade - fatto).days / 30.44)))
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n== Corsi una tantum con attestati che scadono: {len(per_corso)} =="))
        for corso in TrainingCourse.objects.filter(pk__in=list(per_corso)).order_by("codice"):
            righe = per_corso[corso.pk]
            mesi, quanti = Counter(m for _l, m in righe).most_common(1)[0]
            quota = quanti / len(righe)
            desc = f"corso {corso.codice} «{corso.titolo[:60]}»: {quanti}/{len(righe)} attestati a {mesi} mesi"
            if mesi <= 0 or quota < QUOTA_MINIMA:
                self.stdout.write(self.style.WARNING(f"  da vedere a mano: {desc} (durate troppo diverse)"))
                continue
            self.stdout.write(f"  validita' 0 → {mesi} mesi: {desc}")
            self._audit("formazione_validita_corso_allineata", "anagrafica.trainingcourse", corso.pk, {
                "codice": corso.codice, "da": 0, "a": mesi, "attestati": len(righe), "concordi": quanti,
            })
            corso.validita_mesi = mesi
            corso.save(update_fields=["validita_mesi"])
            self.persone.update(lid for lid, _m in righe)
