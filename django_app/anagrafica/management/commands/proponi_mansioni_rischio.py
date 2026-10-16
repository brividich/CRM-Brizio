"""Propone la mansione di rischio delle mansioni lavorative del Mansionario.

Le mansioni lavorative (colonne macchina/processo della skill matrix,
``CompetenzaSkm``) dicono quale mansione di rischio comportano con
``mansioni_rischio``. All'avvio quel collegamento è vuoto. Questo comando lo
ricava dalle persone: per ogni mansione guarda chi è in lista e la mansione di
rischio scritta nella sua anagrafica (quella del medico competente, caricata da
``importa_mansioni_idoneita``), e propone la più frequente.

Regole della proposta:

- solo mansioni attive e ancora **senza** mansione di rischio (``--anche-collegate``
  per rivedere anche le altre: la proposta si aggiunge, non sostituisce);
- conta solo chi ha in anagrafica una voce del catalogo delle mansioni di rischio;
- serve almeno ``--min-persone`` persone (default 1) e la voce più frequente deve
  avere almeno ``--soglia`` per cento di quelle persone (default 50);
- a pari merito tra due voci non si propone niente: si decide a mano.

Cosa comporta: dopo il collegamento, chi è in lista sulla mansione ricava quella
mansione di rischio (DPI, visite, formazione, schede di sicurezza). L'output dice
quante persone in lista hanno in anagrafica una voce diversa: sono quelle a cui
il collegamento aggiunge obblighi.

DRY-RUN di default, ``--commit`` per scrivere. Output e report CSV senza
nominativi: solo mansioni e conteggi.
"""
from __future__ import annotations

import csv
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

ESITI = ("PROPOSTA", "PARI", "SOTTO_SOGLIA", "NESSUNO_A_CATALOGO", "NESSUNO_IN_LISTA", "GIA_COLLEGATA")


def calcola(*, soglia: int = 50, min_persone: int = 1, anche_collegate: bool = False) -> list[dict]:
    """Una riga per mansione lavorativa attiva, con la proposta e il perché."""
    from core.legacy_anagrafica import fetch_anagrafica_rows

    from ...models import AbilitazioneMacchina, CompetenzaSkm, Mansione
    from ...services.mansionario_struttura import TIPI_MANSIONE

    catalogo = {m.nome.strip().casefold(): m for m in Mansione.objects.filter(is_active=True)}
    mansione_di = {
        int(r["id"]): (r.get("mansione") or "").strip().casefold()
        for r in fetch_anagrafica_rows(deduplicate=True) if r.get("id") and r.get("attivo", True)
    }
    persone_per_colonna: dict[int, set[int]] = {}
    for comp_id, lid in (AbilitazioneMacchina.objects
                         .filter(in_lista=True, competenza__isnull=False)
                         .values_list("competenza_id", "legacy_anagrafica_id")):
        persone_per_colonna.setdefault(comp_id, set()).add(int(lid))

    righe = []
    for col in (CompetenzaSkm.objects.filter(tipo__in=TIPI_MANSIONE, attiva=True)
                .select_related("asset", "reparto").prefetch_related("mansioni_rischio")
                .order_by("tipo", "display", "competenza_key")):
        attuali = list(col.mansioni_rischio.all())
        persone = [lid for lid in persone_per_colonna.get(col.pk, set()) if lid in mansione_di]
        conteggi = Counter(mansione_di[lid] for lid in persone if mansione_di[lid] in catalogo)
        riga = {
            "mansione": col, "reparto": col.reparto_effettivo or "", "attuali": attuali,
            "in_lista": len(persone), "a_catalogo": sum(conteggi.values()), "proposta": None,
            "quota": 0, "diverse": 0, "esito": "",
        }
        if attuali and not anche_collegate:
            riga["esito"] = "GIA_COLLEGATA"
        elif not persone:
            riga["esito"] = "NESSUNO_IN_LISTA"
        elif not conteggi:
            riga["esito"] = "NESSUNO_A_CATALOGO"
        else:
            (prima, n1), *resto = conteggi.most_common()
            quota = round(100 * n1 / riga["a_catalogo"])
            riga["quota"] = quota
            if resto and resto[0][1] == n1:
                riga["esito"] = "PARI"
            elif riga["a_catalogo"] < min_persone or quota < soglia:
                riga["esito"] = "SOTTO_SOGLIA"
            else:
                riga["proposta"] = catalogo[prima]
                riga["diverse"] = riga["in_lista"] - n1
                riga["esito"] = "PROPOSTA"
                if any(m.pk == catalogo[prima].pk for m in attuali):
                    riga["esito"] = "GIA_COLLEGATA"
                    riga["proposta"] = None
        righe.append(riga)
    return righe


class Command(BaseCommand):
    help = ("Propone la mansione di rischio delle mansioni lavorative del Mansionario dalla mansione "
            "di rischio delle persone in lista. Dry-run di default, --commit per scrivere.")

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Scrive i collegamenti proposti.")
        parser.add_argument("--soglia", type=int, default=50,
                            help="Quota minima (%%) della mansione di rischio più frequente (default 50).")
        parser.add_argument("--min-persone", type=int, default=1,
                            help="Persone in lista con mansione a catalogo richieste (default 1).")
        parser.add_argument("--anche-collegate", action="store_true",
                            help="Rivede anche le mansioni che hanno già una mansione di rischio (aggiunge, non toglie).")
        parser.add_argument("--report", default="", help="Percorso di un CSV con tutte le righe.")

    def handle(self, *args, **opt):
        righe = calcola(soglia=opt["soglia"], min_persone=opt["min_persone"],
                        anche_collegate=opt["anche_collegate"])
        conteggio = Counter(r["esito"] for r in righe)
        modo = "SCRITTURA" if opt["commit"] else "PROVA (nessuna scrittura)"
        self.stdout.write(f"Mansioni lavorative attive: {len(righe)} — {modo}")
        for r in righe:
            if r["esito"] in ("GIA_COLLEGATA",) and not opt["anche_collegate"]:
                continue
            col = r["mansione"]
            dettaglio = (f"→ {r['proposta'].nome} ({r['quota']}% di {r['a_catalogo']}; "
                         f"{r['diverse']} in lista con altra o nessuna mansione di rischio)"
                         if r["proposta"] else f"in lista {r['in_lista']}, a catalogo {r['a_catalogo']}"
                         + (f", quota {r['quota']}%" if r["quota"] else ""))
            self.stdout.write(f"[{r['esito']}] {col.nome} · {r['reparto'] or 'senza reparto'} {dettaglio}")
        self.stdout.write("Riepilogo: " + ", ".join(f"{e} {conteggio.get(e, 0)}" for e in ESITI))

        if opt["report"]:
            with open(opt["report"], "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(["Mansione", "Tipo", "Reparto", "Esito", "Proposta", "Quota %", "In lista",
                            "Con mansione a catalogo", "Con altra o nessuna", "Già collegate"])
                for r in righe:
                    w.writerow([r["mansione"].nome, r["mansione"].tipo, r["reparto"], r["esito"],
                                r["proposta"].nome if r["proposta"] else "", r["quota"], r["in_lista"],
                                r["a_catalogo"], r["diverse"], ", ".join(m.nome for m in r["attuali"])])
            self.stdout.write(f"Report: {opt['report']}")

        if not opt["commit"]:
            self.stdout.write("Prova: rilancia con --commit per scrivere.")
            return
        proposte = [r for r in righe if r["proposta"]]
        with transaction.atomic():
            for r in proposte:
                r["mansione"].mansioni_rischio.add(r["proposta"])
        try:
            from core.audit import log_action
            log_action(None, "mansionario_proponi_rischio", "anagrafica", {
                "collegate": [[r["mansione"].pk, r["proposta"].pk] for r in proposte],
                "soglia": opt["soglia"], "min_persone": opt["min_persone"],
            }, oggetto_tipo="anagrafica.competenzaskm", oggetto_id="comando")
        except Exception:
            self.stderr.write("Audit non scritto (i collegamenti sono salvati).")
        self.stdout.write(self.style.SUCCESS(f"Collegate {len(proposte)} mansioni lavorative."))
