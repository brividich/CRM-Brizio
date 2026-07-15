"""Allineamento DEV -> PROD dei campi data dell'anagrafica aziendale.

Copre il disallineamento noto: alcuni record ``AnagraficaAziendale`` in prod hanno
``data_prima_assunzione`` e/o ``data_consenso_privacy`` a NULL, mentre in dev sono
valorizzati. Il dipendente e' legato via ``legacy_anagrafica_id`` (unique, stabile
dev<->prod), quindi il match e' diretto, senza rimappare identita'.

SCOPE (deliberatamente stretto):
    * tocca SOLO ``data_prima_assunzione`` e ``data_consenso_privacy``;
    * FILL-ONLY: scrive un campo in prod solo se in prod e' NULL e in dev ha un valore.
      Non sovrascrive MAI un valore gia' presente in prod (nessuna --force di override);
    * NON crea righe: se un ``legacy_anagrafica_id`` del file non esiste in prod, lo
      segnala e lo salta (le righe mancanti sono un problema separato).

Coerenza flag consenso: quando (e solo quando) valorizza ``data_consenso_privacy`` da
dev, se il flag ``consenso_privacy`` in prod e' False lo porta a True — una data di
consenso senza flag e' un record incoerente. Nessun altro campo viene toccato.

Formato di scambio: JSON ``{"righe": [{"legacy_anagrafica_id", "data_prima_assunzione",
"data_consenso_privacy"}, ...]}`` (solo le righe con almeno una delle due date valorizzata).

Uso:
    # su DEV — estrai:
    python manage.py migra_anagrafica_aziendale --export aa_date.json --settings=config.settings.dev
    # su PROD — anteprima (non scrive nulla):
    python manage.py migra_anagrafica_aziendale --import aa_date.json --settings=config.settings.prod
    # su PROD — esegui:
    python manage.py migra_anagrafica_aziendale --import aa_date.json --apply --settings=config.settings.prod

Nota deploy: metti il JSON in un percorso ASSOLUTO fuori da ``current\\`` (il deploy
rinfresca ``current`` e cancellerebbe il file). Il comando .py arriva col deploy del branch.
"""
import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

CAMPI_DATA = ("data_prima_assunzione", "data_consenso_privacy")


class Command(BaseCommand):
    help = "Allinea DEV->PROD i campi data dell'anagrafica aziendale (fill-only, no override)."

    def add_arguments(self, parser):
        parser.add_argument("--export", metavar="FILE", help="Estrai le date da DEV nel FILE.")
        parser.add_argument("--import", dest="imp", metavar="FILE", help="Applica il FILE in PROD.")
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
        from anagrafica.models import DipendenteAnagraficaAziendale

        righe = []
        qs = DipendenteAnagraficaAziendale.objects.values(
            "legacy_anagrafica_id", "data_prima_assunzione", "data_consenso_privacy"
        )
        for r in qs:
            dpa = r["data_prima_assunzione"]
            dcp = r["data_consenso_privacy"]
            if dpa is None and dcp is None:
                continue  # niente da migrare per questa riga
            righe.append({
                "legacy_anagrafica_id": r["legacy_anagrafica_id"],
                "data_prima_assunzione": dpa.isoformat() if dpa else None,
                "data_consenso_privacy": dcp.isoformat() if dcp else None,
            })
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"righe": righe}, fh, ensure_ascii=False, indent=1)
        self.stdout.write(self.style.SUCCESS(
            f"Export: {len(righe)} righe con almeno una data valorizzata -> {path}"))

    # ── PROD ───────────────────────────────────────────────────────────────
    def _import(self, path, *, apply):
        from anagrafica.models import DipendenteAnagraficaAziendale

        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        righe_in = payload.get("righe", [])

        prod = {a.legacy_anagrafica_id: a for a in DipendenteAnagraficaAziendale.objects.all()}

        mancanti = []          # legacy_id nel file ma assenti in prod (saltati)
        set_field = {c: 0 for c in CAMPI_DATA}   # campi che verrebbero riempiti
        gia_valorizzati = {c: 0 for c in CAMPI_DATA}  # prod gia' pieno -> non toccato
        flag_da_settare = 0    # consenso_privacy False -> True in coda al fill della data
        piano = []             # (obj, {campo: date}) da applicare

        for r in righe_in:
            lid = r["legacy_anagrafica_id"]
            obj = prod.get(lid)
            if obj is None:
                mancanti.append(lid)
                continue
            updates = {}
            for campo in CAMPI_DATA:
                dev_val = r.get(campo)
                if dev_val is None:
                    continue
                if getattr(obj, campo) is not None:
                    gia_valorizzati[campo] += 1
                    continue
                updates[campo] = date.fromisoformat(dev_val)
                set_field[campo] += 1
            if updates:
                if "data_consenso_privacy" in updates and not obj.consenso_privacy:
                    flag_da_settare += 1
                piano.append((obj, updates))

        # ---- Report ----
        self.stdout.write("=== ALLINEA ANAGRAFICA AZIENDALE (date) — %s ==="
                          % ("APPLY" if apply else "DRY-RUN"))
        self.stdout.write(f"Righe nel file: {len(righe_in)} | righe da aggiornare in prod: {len(piano)}")
        for campo in CAMPI_DATA:
            self.stdout.write(
                f"  {campo}: da riempire {set_field[campo]} "
                f"| gia' valorizzati in prod (NON toccati) {gia_valorizzati[campo]}")
        self.stdout.write(f"  consenso_privacy: flag portati a True (per coerenza con la data): {flag_da_settare}")
        if mancanti:
            self.stdout.write(self.style.WARNING(
                f"  {len(mancanti)} legacy_id nel file NON esistono in prod (righe non create, saltate): "
                + ", ".join(map(str, sorted(mancanti)[:50]))
                + (" ..." if len(mancanti) > 50 else "")))

        if not apply:
            self.stdout.write(self.style.NOTICE("DRY-RUN: nulla scritto. Rilancia con --apply per eseguire."))
            return

        # ---- Apply (transazione atomica: un errore -> rollback totale) ----
        aggiornati = 0
        with transaction.atomic():
            for obj, updates in piano:
                campi = list(updates)
                for campo, val in updates.items():
                    setattr(obj, campo, val)
                if "data_consenso_privacy" in updates and not obj.consenso_privacy:
                    obj.consenso_privacy = True
                    campi.append("consenso_privacy")
                obj.save(update_fields=campi)
                aggiornati += 1
        self.stdout.write(self.style.SUCCESS(f"FATTO: {aggiornati} righe aggiornate in prod."))
