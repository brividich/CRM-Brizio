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
formazione, MPQ, skill matrix, visite mediche. Esclusa ``TrainingDeadline`` (derivata): dopo l'--apply
sui record di formazione rigenerare le scadenze con:
    python manage.py refresh_training_deadlines --all --settings=config.settings.prod

Uso:
    # su DEV — estrai la mappa:
    python manage.py ripara_legacy_id_import --export mappa_cf.json --settings=config.settings.dev
    # su PROD — anteprima (non scrive nulla):
    python manage.py ripara_legacy_id_import --import mappa_cf.json --settings=config.settings.prod
    # su PROD — esegui:
    python manage.py ripara_legacy_id_import --import mappa_cf.json --apply --settings=config.settings.prod
    # su PROD — report SOLA LETTURA degli errori silenziosi (record 'gia' validi' col CF di un altro):
    python manage.py ripara_legacy_id_import --report mappa_cf.json --settings=config.settings.prod
    # su PROD — DOPO l'--import: ricostruisce la cache scadenze (toglie i "#ID" dallo scadenzario):
    python manage.py ripara_legacy_id_import --rifai-scadenze --apply --settings=config.settings.prod

Nota deploy: metti il JSON in un percorso ASSOLUTO fuori da ``current\\``.
Nota scadenzario: lo scadenzario legge ``TrainingDeadline`` (cache derivata). Dopo
l'``--import`` va rigenerata con ``--rifai-scadenze --apply`` (equivale a svuotarla e
rilanciare ``refresh_training_deadlines --all``), altrimenti restano le voci "#ID" vecchie.
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
    # visite mediche
    "VisitaMedica",
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
        parser.add_argument(
            "--report", metavar="FILE",
            help="Report SOLA LETTURA degli errori silenziosi: record 'gia' validi' il cui "
                 "codice fiscale risale a un'ALTRA persona in prod.")
        parser.add_argument(
            "--rifai-scadenze", dest="rifai", action="store_true",
            help="Ricostruisce da zero la cache scadenze formazione (TrainingDeadline): "
                 "elimina le righe stantie con l'ID sbagliato e rigenera dai record corretti. "
                 "Da lanciare DOPO l'--import.")
        parser.add_argument(
            "--scan", action="store_true",
            help="SOLA LETTURA: passa in rassegna TUTTI i modelli di anagrafica con "
                 "legacy_anagrafica_id e conta gli orfani (ID inesistenti in prod) per ciascuno. "
                 "Serve a scoprire quali moduli sono ancora mal-agganciati dall'import.")
        parser.add_argument(
            "--purge-doppioni", dest="purge", metavar="FILE",
            help="Cancella i record orfani che sono DOPPIONI: un orfano viene eliminato solo se "
                 "esiste gia' il 'gemello' corretto agganciato alla persona giusta (via CF). "
                 "Gli orfani senza gemello NON vengono toccati. Dry-run di default.")

    def handle(self, *args, **o):
        azioni = sum(bool(o.get(k)) for k in ("export", "imp", "report", "rifai", "scan", "purge"))
        if azioni != 1:
            raise CommandError(
                "Specifica ESATTAMENTE una tra --export, --import, --report, --rifai-scadenze, "
                "--scan e --purge-doppioni.")
        if o.get("export"):
            self._export(o["export"])
        elif o.get("imp"):
            self._import(o["imp"], apply=o["apply"])
        elif o.get("report"):
            self._report(o["report"])
        elif o.get("rifai"):
            self._rifai_scadenze(apply=o["apply"])
        elif o.get("purge"):
            self._purge_doppioni(o["purge"], apply=o["apply"])
        else:
            self._scan()

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

    # ── PROD (sola lettura) ─────────────────────────────────────────────────
    def _report(self, path):
        """Elenca i record NON orfani (legacy_id valido in prod) il cui codice fiscale,
        secondo la mappa di dev, appartiene a un'ALTRA persona di prod: possibile
        attribuzione silenziosamente sbagliata (non mostra "#ID", ma e' della persona
        sbagliata). NON scrive nulla: sono casi da valutare a mano, perche' un record
        su #L potrebbe essere legittimo di #L (uso nativo in prod) oppure importato da
        dev e appartenere a #P."""
        from anagrafica.models import DipendenteAnagraficaCivile

        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        devmap = {r["dev_id"]: r for r in payload.get("map", [])}

        prod_cf = {}
        for c in DipendenteAnagraficaCivile.objects.values("legacy_anagrafica_id", "codice_fiscale"):
            cf = _norm_cf(c["codice_fiscale"])
            if cf:
                prod_cf.setdefault(cf, c["legacy_anagrafica_id"])
        nomi_prod = _nomi_legacy()
        prod_ids = set(nomi_prod)

        self.stdout.write("=== REPORT CONFLITTI (possibili errori silenziosi — SOLA LETTURA) ===")
        tot_record = 0
        coppie = set()
        esempi = []
        for name in TARGET_MODELS:
            M = apps.get_model("anagrafica", name)
            pair_count = {}
            for r in M.objects.all():
                L = r.legacy_anagrafica_id
                if L is None or L == 0 or L not in prod_ids:
                    continue  # orfani e esterni: gestiti da --import, non sono errori silenziosi
                info = devmap.get(L)
                cf = _norm_cf(info["cf"]) if info else ""
                if not cf:
                    continue
                P = prod_cf.get(cf)
                if P is None or P == L:
                    continue  # coerente: il CF su #L e' proprio di #L
                pair_count[(L, P)] = pair_count.get((L, P), 0) + 1
            n_rec = sum(pair_count.values())
            if n_rec:
                tot_record += n_rec
                coppie |= set(pair_count)
                self.stdout.write(f"  {name}: {n_rec} record su {len(pair_count)} persone")
                for (L, P), c in sorted(pair_count.items(), key=lambda x: -x[1])[:10]:
                    dev_nome = (devmap.get(L) or {}).get("nome", "?")
                    esempi.append(
                        f"    {name}: ora #{L} ({nomi_prod.get(L, '?')}) — {c} record — "
                        f"il CF risale a #{P} ({nomi_prod.get(P, '?')}) [persona dev: {dev_nome}]")

        self.stdout.write(f"TOTALE record potenzialmente attribuiti alla persona sbagliata: "
                          f"{tot_record} ({len(coppie)} coppie persona)")
        for e in esempi[:60]:
            self.stdout.write(e)
        if tot_record == 0:
            self.stdout.write(self.style.SUCCESS(
                "Nessun conflitto: i record 'gia' validi' sono coerenti col codice fiscale."))
        else:
            self.stdout.write(self.style.WARNING(
                "Questi record NON mostrano #ID ma potrebbero essere della persona sbagliata. "
                "Vanno valutati a mano: un record su #L puo' essere legittimo di #L (uso nativo "
                "in prod) oppure importato da dev e appartenere a #P."))

    # ── PROD (ricostruzione cache scadenze) ─────────────────────────────────
    def _rifai_scadenze(self, *, apply):
        """La scadenza formazione (TrainingDeadline) e' una cache DERIVATA: la sua unica
        fonte e' refresh_deadlines(). Dopo il remap dei record sorgente, il servizio
        rigenera le righe corrette ma NON cancella quelle vecchie (update_or_create) ->
        restano le scadenze "#ID" stantie accanto alle nuove. Qui si ricostruisce da zero:
        elimina l'intera cache e la rigenera dai record ormai corretti."""
        from anagrafica.models_formazione import TrainingDeadline
        from anagrafica.services.training_deadline_service import refresh_deadlines

        prima = TrainingDeadline.objects.count()
        prod_ids = set(_nomi_legacy())
        orfane = TrainingDeadline.objects.exclude(legacy_anagrafica_id__in=prod_ids).count()
        self.stdout.write("=== RIFAI SCADENZE FORMAZIONE (TrainingDeadline) — %s ==="
                          % ("APPLY" if apply else "DRY-RUN"))
        self.stdout.write(f"Scadenze attuali: {prima} | di cui orfane (mostrano #ID): {orfane}")
        if not apply:
            self.stdout.write(self.style.NOTICE(
                "DRY-RUN: nulla scritto. Rilancia con --apply per ricostruire (cancella e rigenera)."))
            return
        with transaction.atomic():
            TrainingDeadline.objects.all().delete()
            rigenerate = refresh_deadlines()
        dopo = TrainingDeadline.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"FATTO: cache ricostruita. Scadenze ora: {dopo} (rigenerate {rigenerate}, "
            f"eliminate {prima} vecchie di cui {orfane} orfane)."))

    # ── PROD (cancellazione doppioni orfani) ────────────────────────────────
    def _purge_doppioni(self, path, *, apply):
        """Cancella i record ORFANI che sono DOPPIONI di uno gia' corretto. Un orfano
        (legacy_id assente in prod) viene eliminato solo se, risalendo il suo CF al numero
        di prod P, esiste gia' un 'gemello' con lo stesso vincolo di unicita' agganciato a
        P: sono i record che il remap ha saltato per collisione (la persona ha gia'
        l'iscrizione corretta). Gli orfani SENZA gemello (o senza CF) NON vengono toccati."""
        from anagrafica.models import DipendenteAnagraficaCivile

        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        devmap = {r["dev_id"]: r for r in payload.get("map", [])}

        prod_cf = {}
        for c in DipendenteAnagraficaCivile.objects.values("legacy_anagrafica_id", "codice_fiscale"):
            cf = _norm_cf(c["codice_fiscale"])
            if cf:
                prod_cf.setdefault(cf, c["legacy_anagrafica_id"])
        nomi_prod = _nomi_legacy()
        prod_ids = set(nomi_prod)

        self.stdout.write("=== PURGE DOPPIONI ORFANI (via codice fiscale) — %s ==="
                          % ("APPLY" if apply else "DRY-RUN"))
        da_cancellare = []      # (Model, pk)
        senza_gemello = 0
        esempi = []
        for name in TARGET_MODELS:
            M = apps.get_model("anagrafica", name)
            uniq_sets = self._uniq_sets(M)
            if not uniq_sets:
                continue  # senza vincolo di unicita' non esiste il concetto di "doppione"
            other_attnames = {
                us: [M._meta.get_field(f).attname for f in us if f != "legacy_anagrafica_id"]
                for us in uniq_sets
            }
            n_mod = 0
            for r in M.objects.all():
                L = r.legacy_anagrafica_id
                if L is None or L == 0 or L in prod_ids:
                    continue  # non orfano
                info = devmap.get(L)
                cf = _norm_cf(info["cf"]) if info else ""
                if not cf:
                    continue  # senza CF: non decidibile, si lascia
                P = prod_cf.get(cf)
                if P is None:
                    continue
                gemello = False
                for us in uniq_sets:
                    filt = {a: getattr(r, a) for a in other_attnames[us]}
                    if M.objects.filter(legacy_anagrafica_id=P, **filt).exclude(pk=r.pk).exists():
                        gemello = True
                        break
                if gemello:
                    da_cancellare.append((M, r.pk))
                    n_mod += 1
                    if len(esempi) < 40:
                        esempi.append(f"    {name}: elimino orfano #{L} "
                                      f"({(info or {}).get('nome', '?')}) — gemello gia' su #{P}")
                else:
                    senza_gemello += 1
            if n_mod:
                self.stdout.write(f"  {name}: {n_mod} doppioni orfani da cancellare")

        self.stdout.write(f"TOTALE doppioni da cancellare: {len(da_cancellare)} "
                          f"| orfani SENZA gemello (non toccati): {senza_gemello}")
        for e in esempi:
            self.stdout.write(e)
        if not apply:
            self.stdout.write(self.style.NOTICE("DRY-RUN: nulla cancellato. Rilancia con --apply per eseguire."))
            return
        with transaction.atomic():
            for M, pk in da_cancellare:
                M.objects.filter(pk=pk).delete()
        self.stdout.write(self.style.SUCCESS(f"FATTO: {len(da_cancellare)} doppioni orfani cancellati."))
        self.stdout.write(self.style.WARNING(
            "Se hai cancellato doppioni di formazione, rilancia '--rifai-scadenze --apply'."))

    # ── PROD (audit sola lettura) ───────────────────────────────────────────
    def _scan(self):
        """Passa in rassegna TUTTI i modelli dell'app anagrafica con un campo
        legacy_anagrafica_id e conta, per ciascuno, le persone il cui ID non esiste tra i
        dipendenti di prod (orfani = tipico segno di un import fatto col legacy_id di dev).
        I modelli identita' (civile/aziendale) e quelli nativi risultano a 0."""
        prod_ids = set(_nomi_legacy())
        self.stdout.write("=== SCAN ORFANI — modelli anagrafica con legacy_anagrafica_id (SOLA LETTURA) ===")
        righe = []
        for M in apps.get_app_config("anagrafica").get_models():
            if not any(getattr(f, "name", None) == "legacy_anagrafica_id" for f in M._meta.get_fields()):
                continue
            ids = set(
                M.objects.exclude(legacy_anagrafica_id__isnull=True)
                .values_list("legacy_anagrafica_id", flat=True)
            )
            ids.discard(0)
            orfani = sum(1 for i in ids if i not in prod_ids)
            righe.append((M.__name__, M.objects.count(), len(ids), orfani))
        righe.sort(key=lambda r: -r[3])
        for name, tot, npers, norf in righe:
            flag = self.style.WARNING("  <-- ORFANI (da valutare)") if norf else ""
            self.stdout.write(f"  {name}: record {tot} | persone {npers} | orfane {norf}{flag}")
        tot_orf = sum(r[3] for r in righe)
        if tot_orf == 0:
            self.stdout.write(self.style.SUCCESS(
                "Nessun modello con orfani: tutti gli agganci persona risolvono in prod."))
        else:
            self.stdout.write(self.style.WARNING(
                f"{tot_orf} persone-orfane totali su {sum(1 for r in righe if r[3])} modelli. "
                "I modelli formazione/visite/MPQ/skill-matrix sono coperti dal remap; per gli altri "
                "valutare se erano importati da dev (allora vanno rimappati) o sono dato nativo di prod."))
