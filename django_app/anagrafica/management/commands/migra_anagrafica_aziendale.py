"""Allineamento DEV -> PROD dei campi data dell'anagrafica aziendale.

Copre il disallineamento noto: in PROD i record ``DipendenteAnagraficaAziendale``
hanno ``data_prima_assunzione`` e/o ``data_consenso_privacy`` per lo piu' a NULL,
mentre in DEV sono valorizzati.

IDENTITA' = CODICE FISCALE (non legacy_anagrafica_id).
``legacy_anagrafica_id`` e' l'``id`` progressivo della tabella legacy
``anagrafica_dipendenti`` ed e' DIVERSO tra dev e prod (lo stesso dipendente ha un
numero diverso nelle due macchine). Agganciare per quel numero sposterebbe le date
sulla persona sbagliata. L'unica identita' stabile e' il ``codice_fiscale`` su
``DipendenteAnagraficaCivile``: il file di scambio e' quindi keyed per codice fiscale,
e in prod si risale codice fiscale -> civile -> legacy_id di prod -> scheda aziendale.

SCOPE (deliberatamente stretto):
    * tocca SOLO ``data_prima_assunzione`` e ``data_consenso_privacy``;
    * FILL-ONLY: scrive un campo in prod solo se in prod e' NULL e in dev ha un valore.
      Non sovrascrive MAI un valore gia' presente in prod;
    * NON crea righe: se in prod il codice fiscale non esiste, o esiste ma senza scheda
      aziendale, la riga viene segnalata e saltata.

Coerenza flag consenso: quando (e solo quando) valorizza ``data_consenso_privacy`` da
dev, se il flag ``consenso_privacy`` in prod e' False lo porta a True — una data di
consenso senza flag e' un record incoerente. Nessun altro campo viene toccato.

Formato di scambio: JSON ``{"righe": [{"codice_fiscale", "nome", "data_prima_assunzione",
"data_consenso_privacy"}, ...]}`` (``nome`` solo per leggibilita' del report; il match e'
sul codice fiscale). Solo le righe con almeno una delle due date valorizzata E con un
codice fiscale noto.

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


def _norm_cf(value):
    return (value or "").strip().upper()


class Command(BaseCommand):
    help = "Allinea DEV->PROD i campi data dell'anagrafica aziendale via codice fiscale (fill-only)."

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
        from django.db import connection

        from anagrafica.models import DipendenteAnagraficaAziendale, DipendenteAnagraficaCivile

        # legacy_id -> codice_fiscale (da civile) e -> nome leggibile (dalla tabella legacy).
        cf_map = {}
        for c in DipendenteAnagraficaCivile.objects.values("legacy_anagrafica_id", "codice_fiscale"):
            cf = _norm_cf(c["codice_fiscale"])
            if cf:
                cf_map[c["legacy_anagrafica_id"]] = cf
        nome_map = {}
        with connection.cursor() as cur:
            cur.execute("SELECT id, nome, cognome FROM anagrafica_dipendenti")
            for _id, _nome, _cognome in cur.fetchall():
                nome_map[_id] = f"{(_cognome or '').strip()} {(_nome or '').strip()}".strip()

        righe = []
        senza_cf = 0
        for r in DipendenteAnagraficaAziendale.objects.values(
            "legacy_anagrafica_id", "data_prima_assunzione", "data_consenso_privacy"
        ):
            dpa, dcp = r["data_prima_assunzione"], r["data_consenso_privacy"]
            if dpa is None and dcp is None:
                continue  # niente da migrare
            cf = cf_map.get(r["legacy_anagrafica_id"])
            if not cf:
                senza_cf += 1  # senza codice fiscale non e' agganciabile a prod
                continue
            righe.append({
                "codice_fiscale": cf,
                "nome": nome_map.get(r["legacy_anagrafica_id"], ""),
                "data_prima_assunzione": dpa.isoformat() if dpa else None,
                "data_consenso_privacy": dcp.isoformat() if dcp else None,
            })
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"righe": righe}, fh, ensure_ascii=False, indent=1)
        msg = f"Export: {len(righe)} righe (agganciate per codice fiscale) -> {path}"
        if senza_cf:
            msg += f"  [ATTENZIONE: {senza_cf} righe con date ma SENZA codice fiscale, escluse]"
        self.stdout.write(self.style.SUCCESS(msg))

    # ── PROD ───────────────────────────────────────────────────────────────
    def _import(self, path, *, apply):
        from anagrafica.models import DipendenteAnagraficaAziendale, DipendenteAnagraficaCivile

        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        righe_in = payload.get("righe", [])

        # PROD: codice fiscale -> legacy_id (via civile), + segnalazione duplicati.
        cf_to_legacy, dup_cf = {}, set()
        for c in DipendenteAnagraficaCivile.objects.values("legacy_anagrafica_id", "codice_fiscale"):
            cf = _norm_cf(c["codice_fiscale"])
            if not cf:
                continue
            if cf in cf_to_legacy and cf_to_legacy[cf] != c["legacy_anagrafica_id"]:
                dup_cf.add(cf)
            cf_to_legacy.setdefault(cf, c["legacy_anagrafica_id"])
        az_by_legacy = {a.legacy_anagrafica_id: a for a in DipendenteAnagraficaAziendale.objects.all()}

        cf_non_trovati = []    # codice fiscale del file assente in prod
        az_mancante = []       # cf trovato ma nessuna scheda aziendale in prod
        set_field = {c: 0 for c in CAMPI_DATA}
        gia_valorizzati = {c: 0 for c in CAMPI_DATA}
        flag_da_settare = 0
        piano = []             # (obj, {campo: date})

        for r in righe_in:
            cf = _norm_cf(r.get("codice_fiscale"))
            nome = (r.get("nome") or "").strip()
            legacy = cf_to_legacy.get(cf)
            if legacy is None:
                cf_non_trovati.append(f"{cf} {nome}".strip())
                continue
            obj = az_by_legacy.get(legacy)
            if obj is None:
                az_mancante.append(f"{cf} {nome}".strip())
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
        agganciate = len(righe_in) - len(cf_non_trovati) - len(az_mancante)
        self.stdout.write("=== ALLINEA ANAGRAFICA AZIENDALE (date, match per codice fiscale) — %s ==="
                          % ("APPLY" if apply else "DRY-RUN"))
        self.stdout.write(f"Righe nel file: {len(righe_in)} | agganciate a una scheda in prod: {agganciate} "
                          f"| righe da aggiornare: {len(piano)}")
        for campo in CAMPI_DATA:
            self.stdout.write(
                f"  {campo}: da riempire {set_field[campo]} "
                f"| gia' valorizzati in prod (NON toccati) {gia_valorizzati[campo]}")
        self.stdout.write(f"  consenso_privacy: flag portati a True (coerenza con la data): {flag_da_settare}")
        if cf_non_trovati:
            self.stdout.write(self.style.WARNING(
                f"  {len(cf_non_trovati)} codici fiscali NON trovati in prod (saltati): "
                + "; ".join(cf_non_trovati[:30]) + (" ..." if len(cf_non_trovati) > 30 else "")))
        if az_mancante:
            self.stdout.write(self.style.WARNING(
                f"  {len(az_mancante)} persone trovate ma SENZA scheda aziendale in prod (saltate): "
                + "; ".join(az_mancante[:30]) + (" ..." if len(az_mancante) > 30 else "")))
        if dup_cf:
            self.stdout.write(self.style.WARNING(
                f"  {len(dup_cf)} codici fiscali DUPLICATI in prod (usata la prima scheda): "
                + ", ".join(sorted(dup_cf)[:20])))

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
