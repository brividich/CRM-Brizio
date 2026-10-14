"""Importa lo storico trimestrale dei contatori MFC dal registro Excel.

Dry-run di default: stampa cosa creerebbe/aggiornerebbe e i cali di contatore.
Le macchine non vengono mai create: una matricola sconosciuta (es. una MFC
sostituita) viene segnalata e saltata. Le letture esistenti restano intatte
salvo --sovrascrivi.
"""
from pathlib import Path
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from contatori import storico_excel
from contatori.models import CONTATORI, LetturaContatori, Macchina

CAMPI = [c[0] for c in CONTATORI]


def _chiave_reparto(testo):
    return re.sub(r"[\s\-_]", "", str(testo or "")).upper()


class Command(BaseCommand):
    help = "Importa lo storico contatori MFC dal registro Excel trimestrale. Dry-run salvo --apply."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Percorso del file .xlsx")
        parser.add_argument("--foglio", default=storico_excel.FOGLIO_DEFAULT)
        parser.add_argument("--apply", action="store_true", help="Scrive le letture (default: simulazione).")
        parser.add_argument("--sovrascrivi", action="store_true",
                            help="Aggiorna le letture gia' presenti per macchina+trimestre.")
        parser.add_argument("--dal", default="", help='Primo trimestre da importare, es. "2024-Q1".')
        parser.add_argument("--mappa", action="append", default=[], metavar="REPARTO=MATRICOLA",
                            help="Abbina le righe senza matricola di un reparto a una macchina.")

    def handle(self, *args, **opts):
        percorso = Path(opts["file"])
        if not percorso.is_file():
            raise CommandError(f"File non trovato: {percorso}")
        try:
            esito = storico_excel.leggi_file(percorso, opts["foglio"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        mappa = {}
        for voce in opts["mappa"]:
            reparto, sep, matricola = voce.partition("=")
            if not sep or not matricola.strip():
                raise CommandError(f"--mappa non valida: «{voce}» (atteso REPARTO=MATRICOLA)")
            mappa[_chiave_reparto(reparto)] = matricola.strip()

        macchine = {m.matricola.upper(): m for m in Macchina.objects.all()}
        per_reparto = {}
        for m in macchine.values():
            per_reparto.setdefault(_chiave_reparto(m.reparto), []).append(m)

        for avviso in esito.avvisi:
            self.stdout.write(self.style.WARNING(f"AVVISO  {avviso}"))

        da_creare, da_aggiornare, uguali, esistenti, ignote = [], [], 0, 0, {}
        for r in esito.righe:
            if opts["dal"] and r.trimestre < opts["dal"]:
                continue
            matricola = r.matricola or mappa.get(_chiave_reparto(r.reparto), "")
            macchina = macchine.get(matricola.upper()) if matricola else None
            if macchina is None and not matricola:
                candidati = per_reparto.get(_chiave_reparto(r.reparto), [])
                macchina = candidati[0] if len(candidati) == 1 else None
            if macchina is None:
                ignote.setdefault(matricola or f"(reparto {r.reparto})", []).append(r.trimestre)
                continue
            valori = {c: getattr(r, c) for c in CAMPI}
            lettura = LetturaContatori.objects.filter(macchina=macchina, trimestre=r.trimestre).first()
            if lettura is None:
                da_creare.append((macchina, r, valori))
            elif all(getattr(lettura, c) == v for c, v in valori.items()):
                uguali += 1
            elif opts["sovrascrivi"]:
                da_aggiornare.append((lettura, r, valori))
            else:
                esistenti += 1
                self.stdout.write(self.style.WARNING(
                    f"DIVERSA {macchina.reparto} {r.trimestre}: a DB "
                    f"{[getattr(lettura, c) for c in CAMPI]}, Excel {list(valori.values())} "
                    "(lasciata; --sovrascrivi per aggiornare)"
                ))

        for matricola, trimestri in sorted(ignote.items()):
            self.stdout.write(self.style.WARNING(
                f"SALTATA matricola {matricola} non presente in anagrafica MFC: "
                f"{len(trimestri)} trimestri ({trimestri[0]} - {trimestri[-1]})"
            ))
        self._controlla_cali(da_creare, da_aggiornare)

        verbo = "CREO" if opts["apply"] else "CREEREI"
        for macchina, r, valori in da_creare:
            self.stdout.write(f"{verbo} {macchina.reparto} [{macchina.matricola}] {r.trimestre} "
                              f"{list(valori.values())} tot {r.totale}")
        for lettura, r, valori in da_aggiornare:
            self.stdout.write(f"{'AGGIORNO' if opts['apply'] else 'AGGIORNEREI'} "
                              f"{lettura.macchina.reparto} {r.trimestre} {list(valori.values())}")

        if opts["apply"]:
            nota = f"Storico Excel {percorso.name}"[:200]
            with transaction.atomic():
                for macchina, r, valori in da_creare:
                    LetturaContatori.objects.create(
                        macchina=macchina, trimestre=r.trimestre, data=r.data,
                        fonte=LetturaContatori.Fonte.MANUALE, note=f"{nota} r.{r.riga_excel}"[:200],
                        **valori,
                    )
                for lettura, r, valori in da_aggiornare:
                    for campo, valore in valori.items():
                        setattr(lettura, campo, valore)
                    lettura.note = f"{nota} r.{r.riga_excel} (aggiornata)"[:200]
                    lettura.save(update_fields=[*CAMPI, "note"])

        self.stdout.write(self.style.SUCCESS(
            f"{'Importate' if opts['apply'] else 'Simulazione'}: {len(da_creare)} nuove, "
            f"{len(da_aggiornare)} aggiornate, {uguali} gia' identiche, {esistenti} diverse lasciate, "
            f"{sum(len(t) for t in ignote.values())} senza macchina."
            + ("" if opts["apply"] else " Rilancia con --apply per scrivere.")
        ))

    def _controlla_cali(self, da_creare, da_aggiornare):
        """Avvisa se, con le nuove letture, un contatore scende da un trimestre al successivo."""
        serie = {}
        toccate = set()
        for macchina, r, valori in da_creare:
            serie.setdefault(macchina.pk, {})[r.trimestre] = valori
            toccate.add(macchina.pk)
        for lettura, r, valori in da_aggiornare:
            serie.setdefault(lettura.macchina_id, {})[r.trimestre] = valori
            toccate.add(lettura.macchina_id)
        nomi = {}
        for lettura in LetturaContatori.objects.filter(macchina_id__in=toccate).select_related("macchina"):
            nomi[lettura.macchina_id] = lettura.macchina.reparto
            serie[lettura.macchina_id].setdefault(
                lettura.trimestre, {c: getattr(lettura, c) for c in CAMPI})
        for macchina, _, _ in da_creare:
            nomi.setdefault(macchina.pk, macchina.reparto)
        for pk in toccate:
            prec = None
            for trimestre in sorted(serie[pk]):
                valori = serie[pk][trimestre]
                if prec:
                    for campo, etichetta in CONTATORI:
                        if valori[campo] < prec[1][campo]:
                            self.stdout.write(self.style.WARNING(
                                f"CALO    {nomi[pk]} {etichetta}: {prec[0]} {prec[1][campo]} -> "
                                f"{trimestre} {valori[campo]}"
                            ))
                prec = (trimestre, valori)
