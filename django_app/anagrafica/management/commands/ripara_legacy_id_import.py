"""Ripara l'aggancio persona<->record dei moduli importati DEV->PROD.

Contesto: gli import DEV->PROD (formazione, MPQ, skill matrix) hanno salvato il
``legacy_anagrafica_id`` DI DEV, che e' l'``id`` progressivo della tabella legacy
``anagrafica_dipendenti`` e in prod appartiene a un'altra persona o a NESSUNO
(nominativo "#ID", "dipendente non esiste"). L'unica identita' stabile e' il
CODICE FISCALE (``DipendenteAnagraficaCivile.codice_fiscale``).

Cosa fa:
    --export (DEV): mappa numero-di-dev -> codice fiscale (+ nome) di TUTTI i dipendenti.
    --import (PROD): per ogni record dei modelli target, se il suo legacy_id e' ORFANO
        (non esiste tra i dipendenti di prod), risale numero-dev -> CF (mappa dev) ->
        numero-prod (civile di prod) e RISCRIVE il legacy_id a quello di prod.

Sicurezza:
    * tocca SOLO gli orfani. I record gia' agganciati a una persona esistente in prod
      NON vengono toccati (contati a parte: vanno verificati a mano);
    * dry-run di default; --apply in transazione atomica (o tutto o niente);
    * anti-doppione: se rimappare violerebbe un vincolo di unicita' del modello
      (persona+corso gia' presente con l'id di prod) il record e' saltato e segnalato;
    * salta ``legacy_id`` NULL e ``0`` (istruttori/qualificatori esterni) e i record
      il cui CF non e' risolvibile in prod;
    * idempotente: dopo la riparazione gli ex-orfani non sono piu' orfani -> una
      riesecuzione li ignora.

Modelli target (persona agganciata via legacy_anagrafica_id nei moduli importati):
formazione, MPQ, skill matrix. Esclusa ``TrainingDeadline`` (derivata): dopo l'--apply
sui record di formazione rigenerare le scadenze con:
    python manage.py refresh_training_deadlines --all --settings=config.settings.prod

Uso:
    # su DEV — estrai la mappa:
    python manage.py ripara_legacy_id_import --export mappa_cf.json --settings=config.settings.dev
    # su PROD — anteprima (non scrive nulla):
    python manage.py ripara_legacy_id_import --import mappa_cf.json --settings=config.settings.prod
    # su PROD — esegui:
    python manage.py ripara_legacy_id_import --import mappa_cf.json --apply --settings=config.settings.prod

Nota deploy: metti il JSON in un percorso ASSOLUTO fuori da ``current\\``.
"""
import json

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import UniqueConstraint

# Modelli (app anagrafica) i cui record sono stati importati con il legacy_id di dev.
TARGET_MODELS = [
    # formazione
    "TrainingRequirementRule", "TrainingInstructor", "TrainingAssignment",
    "TrainingEnrollment", "TrainingLessonAttendance", "TrainingEmployeeRecord",
    "TrainingCertificate",
    # MPQ
    "AbilitazioneProcesso",
    # skill matrix
    "AbilitazioneMacchina", "AbilitazioneMacchinaStorico", "ContinuitaOperativa",
    "SkmCorsiAttivati",
]


def _norm_cf(value):
    return (value or "").strip().upper()


def _nomi_legacy():
    """id legacy -> 'COGNOME NOME' dalla tabella legacy anagrafica_dipendenti."""
    nomi = {}
    with connection.cursor() as cur:
        cur.execute("SELECT id, nome, cognome FROM anagrafica_dipendenti")
        for _id, _nome, _cognome in cur.fetchall():
            nomi[_id] = f"{(_cognome or '').strip()} {(_nome or '').strip()}".strip()
    return nomi


class Command(BaseCommand):
    help = "Ripara (via codice fiscale) il legacy_anagrafica_id dei moduli importati DEV->PROD."

    def add_arguments(self, parser):
        parser.add_argument("--export", metavar="FILE", help="Estrai da DEV la mappa numero->CF.")
        parser.add_argument("--import", dest="imp", metavar="FILE", help="Applica il remap in PROD.")
        parser.add_argument("--apply", action="store_true", help="Esegui davvero (default: dry-run).")

    def handle(self, *args, **o):
        if bool(o.get("export")) == bool(o.get("imp")):
            raise CommandError("Specifica ESATTAMENTE uno tra --export e --import.")
        if o.get("export"):
            self._export(o["export"])
        else:
            self._import(o["imp"], apply=o["apply"])

    # ── DEV ────────────────────────────────────────────────────────────────
    def _export(self, path):
        from anagrafica.models import DipendenteAnagraficaCivile

        nomi = _nomi_legacy()
        righe = []
        for c in DipendenteAnagraficaCivile.objects.values("legacy_anagrafica_id", "codice_fiscale"):
            cf = _norm_cf(c["codice_fiscale"])
            if not cf:
                continue
            lid = c["legacy_anagrafica_id"]
            righe.append({"dev_id": lid, "cf": cf, "nome": nomi.get(lid, "")})
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"map": righe}, fh, ensure_ascii=False, indent=1)
        self.stdout.write(self.style.SUCCESS(
            f"Export: mappa di {len(righe)} dipendenti (numero-dev -> codice fiscale) -> {path}"))

    # ── PROD ───────────────────────────────────────────────────────────────
    def _uniq_sets(self, M):
        """Insiemi di campi che formano unicita' e che includono legacy_anagrafica_id."""
        sets = []
        for ut in M._meta.unique_together:
            if "legacy_anagrafica_id" in ut:
                sets.append(tuple(ut))
        for con in M._meta.constraints:
            if isinstance(con, UniqueConstraint) and "legacy_anagrafica_id" in con.fields:
                sets.append(tuple(con.fields))
        try:
            if M._meta.get_field("legacy_anagrafica_id").unique:
                sets.append(("legacy_anagrafica_id",))
        except Exception:
            pass
        return sets

    def _import(self, path, *, apply):
        from anagrafica.models import DipendenteAnagraficaCivile

        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        devmap = {r["dev_id"]: r for r in payload.get("map", [])}  # dev_id -> {cf, nome}

        # PROD: codice fiscale -> numero di prod (via civile).
        prod_cf = {}
        for c in DipendenteAnagraficaCivile.objects.values("legacy_anagrafica_id", "codice_fiscale"):
            cf = _norm_cf(c["codice_fiscale"])
            if cf:
                prod_cf.setdefault(cf, c["legacy_anagrafica_id"])
        nomi_prod = _nomi_legacy()
        prod_ids = set(nomi_prod)

        plan = []          # (Model, pk, nuovo_id)
        totali = {}        # per-modello: dict di contatori
        esempi = []        # righe di anteprima (max 40)

        self.stdout.write("=== RIPARA LEGACY_ID IMPORT (match per codice fiscale) — %s ==="
                          % ("APPLY" if apply else "DRY-RUN"))

        for name in TARGET_MODELS:
            M = apps.get_model("anagrafica", name)
            uniq_sets = self._uniq_sets(M)
            other_attnames = {
                us: [M._meta.get_field(f).attname for f in us if f != "legacy_anagrafica_id"]
                for us in uniq_sets
            }
            cnt = dict(totale=0, gia_validi=0, esterni=0, senza_cf=0, cf_non_in_prod=0,
                       collisioni=0, da_rimappare=0)

            for r in M.objects.all():
                cnt["totale"] += 1
                L = r.legacy_anagrafica_id
                if L is None or L == 0:
                    cnt["esterni"] += 1
                    continue
                if L in prod_ids:
                    cnt["gia_validi"] += 1
                    continue  # non orfano: non si tocca
                info = devmap.get(L)
                cf = _norm_cf(info["cf"]) if info else ""
                if not cf:
                    cnt["senza_cf"] += 1
                    continue
                P = prod_cf.get(cf)
                if P is None:
                    cnt["cf_non_in_prod"] += 1
                    continue
                if P == L:
                    cnt["gia_validi"] += 1
                    continue
                # anti-doppione: rimappare a P non deve violare un vincolo di unicita'.
                collisione = False
                for us in uniq_sets:
                    filt = {a: getattr(r, a) for a in other_attnames[us]}
                    if M.objects.filter(legacy_anagrafica_id=P, **filt).exclude(pk=r.pk).exists():
                        collisione = True
                        break
                if collisione:
                    cnt["collisioni"] += 1
                    continue
                plan.append((M, r.pk, P))
                cnt["da_rimappare"] += 1
                if len(esempi) < 40:
                    esempi.append(
                        f"    {name}: #{L} ({info.get('nome','?')}) -> #{P} ({nomi_prod.get(P,'?')})")

            totali[name] = cnt
            if cnt["totale"]:
                self.stdout.write(
                    f"  {name}: {cnt['totale']} record | da rimappare {cnt['da_rimappare']} "
                    f"| gia' validi {cnt['gia_validi']} | senza CF {cnt['senza_cf']} "
                    f"| CF non in prod {cnt['cf_non_in_prod']} | collisioni {cnt['collisioni']} "
                    f"| esterni/null {cnt['esterni']}")

        tot_rimap = sum(c["da_rimappare"] for c in totali.values())
        self.stdout.write(f"TOTALE record da rimappare: {tot_rimap}")
        if esempi:
            self.stdout.write("  Esempi (max 40):")
            for e in esempi:
                self.stdout.write(e)

        if not apply:
            self.stdout.write(self.style.NOTICE("DRY-RUN: nulla scritto. Rilancia con --apply per eseguire."))
            return

        with transaction.atomic():
            for M, pk, P in plan:
                M.objects.filter(pk=pk).update(legacy_anagrafica_id=P)
        self.stdout.write(self.style.SUCCESS(f"FATTO: {tot_rimap} record rimappati in prod."))
        self.stdout.write(self.style.WARNING(
            "Ricorda: sui record di formazione rigenera le scadenze derivate con "
            "'refresh_training_deadlines --all'."))
