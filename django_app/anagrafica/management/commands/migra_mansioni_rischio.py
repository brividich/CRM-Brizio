"""Migrazione dati: profilo di rischio delle mansioni → mansioni di rischio (1:1).

Per ogni ``Mansione`` con un profilo di rischio non vuoto (DPI e visite
richieste direttamente, fattori delle esposizioni di mansione attive) crea una
``MansioneRischio`` «<nome> (profilo DVR)» con lo stesso contenuto e la collega.
I campi deprecati della mansione **non vengono toccati**: il rollback è sicuro.

Modalità (default ``--dry-run``)::

    manage.py migra_mansioni_rischio                    # dry-run + report a console
    manage.py migra_mansioni_rischio --report out.csv   # anche CSV
    manage.py migra_mansioni_rischio --apply
    manage.py migra_mansioni_rischio --verifica         # equivalenza vecchio/nuovo motore
    manage.py migra_mansioni_rischio --rollback [--apply]

Esiti per mansione: MAPPATO (creata ora o da creare), GIA_MIGRATO, DIVERGENTE
(già migrata ma il profilo legacy è cambiato: non sovrascritta), DA_DECIDERE
(serve una persona: esposizioni con note o inattive, mansione inattiva ancora
usata), SKIP_VUOTO (nessun profilo). In coda: nomi di mansione dei dipendenti
che non trovano nessuna mansione a catalogo (NON_MAPPATO_DIPENDENTE).

Idempotente: la chiave naturale è ``MansioneRischio.origine_mansione``. Ogni
mansione gira in una transazione sua (transazioni piccole su SQL Server).
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


def profilo_legacy(mansione) -> dict[str, list[int]]:
    """Profilo di rischio dai campi deprecati, in forma canonica (id ordinati)."""
    try:
        dpi = sorted(mansione.dpi_richiesti.values_list("pk", flat=True))
    except Exception:
        dpi = []
    return {
        "dpi": dpi,
        "visite": sorted(mansione.visite_richieste.values_list("pk", flat=True)),
        "fattori": sorted(set(
            mansione.esposizioni_rischio.filter(is_active=True, fattore__is_active=True)
            .values_list("fattore_id", flat=True)
        )),
    }


def impronta(profilo: dict[str, list[int]]) -> str:
    return hashlib.sha256(json.dumps(profilo, sort_keys=True).encode()).hexdigest()


def profilo_mansione_rischio(mr) -> dict[str, list[int]]:
    try:
        dpi = sorted(mr.categorie_dpi.values_list("pk", flat=True))
    except Exception:
        dpi = []
    return {
        "dpi": dpi,
        "visite": sorted(mr.visite.values_list("pk", flat=True)),
        "fattori": sorted(mr.fattori.values_list("pk", flat=True)),
    }


class Command(BaseCommand):
    help = "Migra il profilo di rischio delle mansioni nelle mansioni di rischio (dry-run di default)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive davvero (senza: dry-run).")
        parser.add_argument("--rollback", action="store_true", help="Rimuove ciò che la migrazione ha creato.")
        parser.add_argument("--verifica", action="store_true", help="Confronta i requisiti vecchio/nuovo motore.")
        parser.add_argument("--report", default="", help="Percorso CSV del report.")
        parser.add_argument("--mansione", type=int, action="append", dest="mansioni", help="Solo questa mansione (id).")

    def handle(self, *args, **opts):
        if opts["rollback"] and opts["verifica"]:
            raise CommandError("--rollback e --verifica non vanno insieme.")
        if opts["verifica"]:
            return self._verifica(opts)
        righe = self._rollback(opts) if opts["rollback"] else self._migra(opts)
        self._stampa(righe, opts)

    # ── Migrazione ──────────────────────────────────────────────────────────
    def _mansioni(self, opts):
        from anagrafica.models import Mansione
        qs = Mansione.objects.all().order_by("pk")
        if opts.get("mansioni"):
            qs = qs.filter(pk__in=opts["mansioni"])
        return list(qs)

    def _uso_dipendenti(self) -> Counter:
        try:
            from core.legacy_anagrafica import fetch_anagrafica_rows
            return Counter(
                str(r.get("mansione") or "").strip().casefold()
                for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo", True)
            )
        except Exception:
            return Counter()

    def _migra(self, opts) -> list[dict]:
        from anagrafica.models import MansioneLavorativaRischio, MansioneRischio

        applica = opts["apply"]
        uso = self._uso_dipendenti()
        righe = []
        for mansione in self._mansioni(opts):
            profilo = profilo_legacy(mansione)
            hash_ = impronta(profilo)
            n_dip = uso.get(mansione.nome.strip().casefold(), 0)
            riga = {"mansione_id": mansione.pk, "nome": mansione.nome, "n_dipendenti": n_dip,
                    "n_dpi": len(profilo["dpi"]), "n_visite": len(profilo["visite"]),
                    "n_fattori": len(profilo["fattori"]), "hash": hash_[:12], "esito": "",
                    "mansione_rischio_id": "", "note": ""}
            righe.append(riga)
            esistente = MansioneRischio.objects.filter(origine_mansione=mansione).first()
            if esistente is not None:
                riga["mansione_rischio_id"] = esistente.pk
                riga["esito"] = "GIA_MIGRATO" if esistente.origine_migrazione_hash == hash_ else "DIVERGENTE"
                if riga["esito"] == "DIVERGENTE":
                    riga["note"] = "Profilo legacy cambiato dopo la migrazione: verificare a mano"
                continue
            if not any(profilo.values()):
                riga["esito"] = "SKIP_VUOTO"
                continue
            dubbi = []
            esposizioni = mansione.esposizioni_rischio.all()
            if any((e.note or "").strip() for e in esposizioni):
                dubbi.append("esposizioni con note")
            if not mansione.is_active and n_dip:
                dubbi.append(f"mansione inattiva usata da {n_dip} dipendenti")
            note = list(dubbi)
            if any(not e.is_active for e in esposizioni):
                note.append("esposizioni inattive ignorate (come oggi)")
            riga["esito"] = "DA_DECIDERE" if dubbi else "MAPPATO"
            riga["note"] = "; ".join(note)
            if not applica or dubbi:
                continue
            with transaction.atomic():
                codice = f"MR-{mansione.pk:04d}"
                if MansioneRischio.objects.filter(codice=codice).exists():
                    riga["esito"], riga["note"] = "DA_DECIDERE", f"codice {codice} già usato"
                    continue
                mr = MansioneRischio.objects.create(
                    codice=codice, nome=f"{mansione.nome} (profilo DVR)"[:150],
                    descrizione=f"Generata dalla mansione «{mansione.nome}» (migrazione dati).",
                    origine_mansione=mansione, origine_migrazione_hash=hash_,
                )
                mr.visite.set(profilo["visite"])
                mr.fattori.set(profilo["fattori"])
                if profilo["dpi"]:
                    mr.categorie_dpi.set(profilo["dpi"])
                MansioneLavorativaRischio.objects.create(
                    mansione=mansione, mansione_rischio=mr, ordine=0, origine_migrazione=True,
                    note="Collegamento creato dalla migrazione dati",
                )
                riga["mansione_rischio_id"] = mr.pk
        # Nomi di mansione dei dipendenti senza corrispondenza a catalogo.
        from anagrafica.models import Mansione
        catalogo = {n.strip().casefold() for n in Mansione.objects.values_list("nome", flat=True)}
        for nome, n in sorted(uso.items()):
            if nome and nome not in catalogo:
                righe.append({"mansione_id": "", "nome": nome, "n_dipendenti": n, "n_dpi": "", "n_visite": "",
                              "n_fattori": "", "hash": "", "esito": "NON_MAPPATO_DIPENDENTE",
                              "mansione_rischio_id": "", "note": "Mansione del dipendente non a catalogo"})
        return righe

    # ── Rollback ────────────────────────────────────────────────────────────
    def _rollback(self, opts) -> list[dict]:
        from anagrafica.models import MansioneRischio, TrainingRequirementRule

        applica = opts["apply"]
        righe = []
        qs = MansioneRischio.objects.filter(origine_mansione__isnull=False).select_related("origine_mansione")
        if opts.get("mansioni"):
            qs = qs.filter(origine_mansione_id__in=opts["mansioni"])
        for mr in qs.order_by("pk"):
            riga = {"mansione_id": mr.origine_mansione_id, "nome": mr.nome, "mansione_rischio_id": mr.pk,
                    "esito": "", "note": ""}
            righe.append(riga)
            motivi = []
            if impronta(profilo_mansione_rischio(mr)) != mr.origine_migrazione_hash:
                motivi.append("contenuto modificato dopo la migrazione")
            if mr.link_mansioni.filter(origine_migrazione=False).exists():
                motivi.append("collegamenti manuali")
            if mr.override_dipendenti.exists():
                motivi.append("override individuali")
            if TrainingRequirementRule.objects.filter(mansione_rischio=mr).exists():
                motivi.append("regole formative")
            if motivi:
                riga["esito"], riga["note"] = "NON_ROLLBACKABILE", "; ".join(motivi)
                continue
            riga["esito"] = "RIMOSSO" if applica else "DA_RIMUOVERE"
            if applica:
                with transaction.atomic():
                    mr.link_mansioni.filter(origine_migrazione=True).delete()
                    mr.delete()
        return righe

    # ── Verifica equivalenza ───────────────────────────────────────────────
    def _verifica(self, opts):
        from anagrafica.services import mansionario

        differenze = 0
        for mansione in self._mansioni(opts):
            nuovo = mansionario.requisiti_mansione(mansione)
            vecchio = mansionario.requisiti_mansione_legacy(mansione)
            diff = {}
            for dominio in ("dpi", "visite", "corsi", "piani", "fattori"):
                a = {o.pk for o in vecchio[dominio]}
                b = {o.pk for o in nuovo[dominio]}
                if a != b:
                    diff[dominio] = {"solo_legacy": sorted(a - b), "solo_nuovo": sorted(b - a)}
            if diff:
                differenze += 1
                self.stdout.write(self.style.WARNING(f"«{mansione.nome}» (#{mansione.pk}): {diff}"))
        if differenze:
            self.stdout.write(self.style.WARNING(f"{differenze} mansioni con requisiti diversi fra i due motori."))
        else:
            self.stdout.write(self.style.SUCCESS("Equivalenza verificata: 0 differenze."))
        return None

    # ── Output ──────────────────────────────────────────────────────────────
    def _stampa(self, righe: list[dict], opts) -> None:
        modo = "ROLLBACK" if opts["rollback"] else "MIGRAZIONE"
        modo += "" if opts["apply"] else " (dry-run: nessuna scrittura)"
        self.stdout.write(f"== {modo} ==")
        for r in righe:
            self.stdout.write(f"[{r['esito']}] #{r.get('mansione_id', '')} «{r['nome']}»"
                              f"{' → MR #' + str(r['mansione_rischio_id']) if r.get('mansione_rischio_id') else ''}"
                              f"{' — ' + r['note'] if r.get('note') else ''}")
        totali = Counter(r["esito"] for r in righe)
        self.stdout.write("Totali: " + ", ".join(f"{k}={v}" for k, v in sorted(totali.items())))
        if opts.get("report"):
            campi = list(righe[0].keys()) if righe else ["esito"]
            with open(opts["report"], "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=campi, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(righe)
            self.stdout.write(f"Report CSV: {opts['report']}")
