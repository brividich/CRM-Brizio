"""Converte il «Registro SMS_Suggestion Corner.csv» storico nel JSON per l'import.

Il CSV di export è **doppiamente codificato** (ogni riga fisica racchiusa tra
virgolette, virgolette interne raddoppiate `""`) e ha **celle multi-riga**
(OPPORTUNITY/PLAN/DO che vanno a capo). Questo comando:

1. raggruppa le righe fisiche in record (regex di inizio `"<id>,""<data>""`);
2. ricostruisce ogni record (togliendo un livello di codifica) e lo parsa;
   i record con testo multi-riga «spezzato» sono recuperati leggendo i primi 4
   campi e gli ultimi 23 da posizioni fisse (la rottura tocca solo il corpo
   testuale in mezzo, non i dati strutturati) — **best-effort**, marcati;
3. risolve i **nomi** Incaricato/Controllore/Autore in utenti del portale via
   `anagrafica_dipendenti` (aliasusername = username, provando nome/cognome nei
   due ordini); chi non matcha resta senza username (import lo lascia vuoto);
4. deriva lo **stato** PDCA dai flag P/D/C/A + esiti;
5. scrive il JSON (default: nello scratchpad, MAI nel repo — contiene nomi reali).

Poi: `import_suggestion_corner_legacy --file <json>` (dry-run) → `--apply`.

Nessuna scrittura sul DB: sola lettura dell'anagrafica per risolvere i nomi.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata

from django.core.management.base import BaseCommand, CommandError

# Ordine colonne del registro storico (32 colonne)
COL = {
    "id": 0, "data": 1, "sms": 2, "reparto_prov": 3,
    "opportunity": 4, "plan": 5, "do": 6, "check": 7, "act": 8,
    "P": 9, "D": 10, "C": 11, "A": 12,
    "incaricato": 13, "controllore": 14,
    "data_do": 15, "data_check": 16, "data_esec_do": 17, "data_esec_check": 18,
    "esito_check": 19, "esito_do": 20,
    "nuova_da_act": 21, "vuoi_act": 22, "allegato": 23, "reparto_dest": 24,
    "da_portale": 25, "data_mod": 26, "autore": 27,
    "sollecito_check": 28, "sollecito_do": 29, "scaduto_c": 30, "scaduto_d": 31,
}
N_COLS = 32
N_TAIL = N_COLS - COL["P"]  # 23 colonne finali sempre integre (P..ScadutoD)

START = re.compile(r'^"?\d+,""\d{1,2}/\d{1,2}/\d{4}""')

_ESITO_CHECK = {"positivo": "POSITIVO", "negativo": "NEGATIVO", "rinviato": "RINVIATO"}
_ESITO_DO = {"si": "SI", "sì": "SI", "no": "NO"}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(str(s or "")).casefold()).strip()


def _vero(v: str) -> bool:
    return str(v or "").strip().casefold() == "vero"


def _iso_date(v: str) -> str:
    """DD/MM/YYYY → YYYY-MM-DD; stringa vuota se non parsabile."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(v or ""))
    if not m:
        return ""
    d, mth, y = m.groups()
    return f"{y}-{int(mth):02d}-{int(d):02d}"


class Command(BaseCommand):
    help = "Converte il registro SMS storico (CSV) nel JSON per import_suggestion_corner_legacy."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Percorso del CSV storico.")
        parser.add_argument("--out", required=True, help="Percorso del JSON di output (fuori dal repo).")

    # --- parsing CSV robusto ------------------------------------------------
    def _blocchi(self, raw_lines):
        blocks, cur = [], []
        for line in raw_lines:
            if START.match(line):
                if cur:
                    blocks.append(cur)
                cur = [line]
            elif cur:
                cur.append(line)
        if cur:
            blocks.append(cur)
        return blocks

    def _parse_block(self, block):
        chunks = []
        for s in block:
            if s.startswith('"'):
                s = s[1:]
            if s.endswith('"'):
                s = s[:-1]
            chunks.append(s)
        joined = "\n".join(chunks)
        undoubled = joined.replace('""', '"')
        return next(csv.reader(io.StringIO(undoubled)))

    def _normalizza_campi(self, fields):
        """Restituisce (record_a_32_campi, imperfetto: bool).

        Testa/coda (primi 4 + ultimi 23) sono sempre affidabili; il corpo testuale
        centrale (5 celle) può risultare accorpato nei record multi-riga spezzati.
        """
        if len(fields) == N_COLS:
            return fields, False
        head = fields[:4]
        tail = fields[-N_TAIL:] if len(fields) >= N_TAIL + 4 else fields[4:]
        middle = fields[4:len(fields) - N_TAIL] if len(fields) >= N_TAIL + 4 else []
        # rimappo le 5 celle testuali sulle posizioni disponibili
        text5 = (middle + [""] * 5)[:5]
        if len(tail) < N_TAIL:
            tail = (tail + [""] * N_TAIL)[:N_TAIL]
        return head + text5 + tail, True

    # --- risoluzione nomi ---------------------------------------------------
    def _mappa_nomi(self):
        mappa = {}
        try:
            from core.legacy_models import AnagraficaDipendente
            for d in AnagraficaDipendente.objects.all():
                alias = (d.aliasusername or "").strip()
                if not alias:
                    continue
                nome, cognome = (d.nome or "").strip(), (d.cognome or "").strip()
                for key in (_norm_name(f"{nome} {cognome}"), _norm_name(f"{cognome} {nome}")):
                    if key:
                        mappa.setdefault(key, alias)
        except Exception as exc:  # tabella legacy assente (es. dev SQLite)
            self.stderr.write(self.style.WARNING(
                f"Anagrafica non leggibile ({exc}): i nomi non verranno risolti."))
        return mappa

    # --- derivazione stato --------------------------------------------------
    def _stato(self, rec_fields):
        A = _vero(rec_fields[COL["A"]])
        C = _vero(rec_fields[COL["C"]])
        D = _vero(rec_fields[COL["D"]])
        P = _vero(rec_fields[COL["P"]])
        esito_check = rec_fields[COL["esito_check"]].strip()
        if A:
            return "CHIUSA"
        if C and esito_check:
            return "CHECK_COMPLETATO"
        if D:
            return "DO_COMPLETATO"
        if P:
            return "PLAN_DEFINITO"
        return "DA_CLASSIFICARE"

    def handle(self, *args, **opts):
        try:
            raw = open(opts["file"], encoding="utf-8-sig").read().splitlines()
        except Exception as exc:
            raise CommandError(f"Impossibile leggere {opts['file']}: {exc}")

        blocks = self._blocchi(raw)
        if not blocks:
            raise CommandError("Nessun record riconosciuto nel CSV.")

        nomi = self._mappa_nomi()

        def username(nome):
            return nomi.get(_norm_name(nome), "")

        records, imperfetti, nomi_non_risolti = [], [], set()
        # l'header non viene catturato come blocco (la regex START non lo matcha):
        # blocks[0] è già il primo record.
        for block in blocks:
            try:
                fields = self._parse_block(block)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Parse errore su blocco: {exc}"))
                continue
            fields, imperfetto = self._normalizza_campi(fields)

            def g(name):
                return fields[COL[name]].strip()

            sms = g("sms").upper()
            stato_sms = sms if sms in ("SMS_SI", "SMS_NO") else "DA_GESTIRE"

            rec = {
                "sharepoint_id": int(g("id")) if g("id").isdigit() else None,
                "data_segnalazione": _iso_date(g("data")),
                "reparto_provenienza": g("reparto_prov"),
                "reparto_destinazione": g("reparto_dest"),
                "opportunity": g("opportunity"),
                "plan_testo": g("plan"),
                "do_testo": g("do"),
                "check_testo": g("check"),
                "act_testo": g("act"),
                "stato_sms": stato_sms,
                "esito_check": _ESITO_CHECK.get(g("esito_check").casefold(), ""),
                "esito_do": _ESITO_DO.get(g("esito_do").casefold(), ""),
                "stato": self._stato(fields),
            }
            # persone (nome → username via anagrafica)
            for csv_col, prefix in (("incaricato", "incaricato"),
                                    ("controllore", "controllore"),
                                    ("autore", "autore")):
                nome = g(csv_col)
                if nome:
                    u = username(nome)
                    if u:
                        rec[f"{prefix}_username"] = u
                    else:
                        nomi_non_risolti.add(nome)
                    rec[f"{prefix}_nome"] = nome  # tracciabilità
            # allegato di rete → lista
            alleg = g("allegato")
            if alleg:
                rec["allegati"] = [alleg]

            records.append(rec)
            if imperfetto:
                imperfetti.append(rec["sharepoint_id"])

        with open(opts["out"], "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Convertiti {len(records)} record → {opts['out']}"))
        self.stdout.write(f"  Record con testo imperfetto (best-effort): {len(imperfetti)} → {sorted(x for x in imperfetti if x)}")
        self.stdout.write(f"  Nomi non risolti in anagrafica ({len(nomi_non_risolti)}): {sorted(nomi_non_risolti)}")
