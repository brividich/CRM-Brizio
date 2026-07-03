"""Fase 2 — Migrazione VISITE MEDICHE DEV → PROD con MERGE PER NOME dei tipi visita.

Prod ha gia' i suoi ``TipoVisitaMedica`` (match per ``nome``, unique): questo comando
NON li sovrascrive. Aggiunge solo i tipi dev mancanti e carica le ``VisitaMedica``
riagganciando il ``tipo`` PER NOME. Il dipendente resta legato via ``legacy_anagrafica_id``
(stabile dev↔prod). Le FK a file/utente (``referto_documento``, ``created_by``,
``updated_by``) vengono ANNULLATE.

Formato di scambio: JSON semplice ``{"tipi": [...], "visite": [...]}`` (le visite
referenziano il tipo per NOME, cosi' il match avviene su prod).

Uso:
    # su DEV — estrai:
    python manage.py migra_visite --export visite_export.json --settings=config.settings.dev
    # su PROD — anteprima (non scrive):
    python manage.py migra_visite --import visite_export.json --settings=config.settings.prod
    # su PROD — esegui:
    python manage.py migra_visite --import visite_export.json --apply --settings=config.settings.prod

Opzioni:
    --crea-ruoli-mancanti  crea in prod i RuoloOperativo citati dai tipi dev ma assenti
                           (default: NO — si mappano solo quelli gia' esistenti, il resto
                           viene saltato e segnalato, per non inquinare il catalogo ruoli).
    --force                consente l'import anche se prod ha gia' delle VisitaMedica
                           (default: rifiuta, per evitare doppioni).
"""
import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Fase 2: migrazione visite mediche DEV->PROD (merge per nome dei tipi)."

    def add_arguments(self, parser):
        parser.add_argument("--export", metavar="FILE", help="Estrai le visite da DEV nel FILE.")
        parser.add_argument("--import", dest="imp", metavar="FILE", help="Importa il FILE in PROD.")
        parser.add_argument("--apply", action="store_true", help="Esegui davvero (default: dry-run).")
        parser.add_argument("--crea-ruoli-mancanti", action="store_true",
                            help="Crea i RuoloOperativo mancanti citati dai tipi (default: no).")
        parser.add_argument("--force", action="store_true",
                            help="Importa anche se prod ha gia' delle VisitaMedica.")

    def handle(self, *args, **o):
        if bool(o.get("export")) == bool(o.get("imp")):
            raise CommandError("Specifica ESATTAMENTE uno tra --export e --import.")
        if o.get("export"):
            self._export(o["export"])
        else:
            self._import(o["imp"], apply=o["apply"], crea_ruoli=o["crea_ruoli_mancanti"], force=o["force"])

    # ── DEV ────────────────────────────────────────────────────────────────
    def _export(self, path):
        from anagrafica.models import TipoVisitaMedica, VisitaMedica

        tipi = []
        for t in TipoVisitaMedica.objects.all().prefetch_related("ruoli_operativi"):
            tipi.append({
                "nome": t.nome,
                "descrizione": t.descrizione,
                "durata_mesi": t.durata_mesi,
                "obbligatoria": t.obbligatoria,
                "is_active": t.is_active,
                "ruoli": sorted(r.nome for r in t.ruoli_operativi.all()),
            })
        visite = []
        for v in VisitaMedica.objects.all().select_related("tipo"):
            visite.append({
                "legacy_anagrafica_id": v.legacy_anagrafica_id,
                "tipo_nome": v.tipo.nome,
                "data_svolgimento": v.data_svolgimento.isoformat() if v.data_svolgimento else None,
                "esito": v.esito,
                "prescrizioni": v.prescrizioni,
                "medico_competente": v.medico_competente,
                "note": v.note,
            })
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"tipi": tipi, "visite": visite}, fh, ensure_ascii=False, indent=1)
        self.stdout.write(self.style.SUCCESS(
            f"Export: {len(tipi)} tipi, {len(visite)} visite -> {path}"))

    # ── PROD ───────────────────────────────────────────────────────────────
    def _import(self, path, *, apply, crea_ruoli, force):
        from anagrafica.models import RuoloOperativo, TipoVisitaMedica, VisitaMedica

        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        tipi_in = payload.get("tipi", [])
        visite_in = payload.get("visite", [])

        esistenti = VisitaMedica.objects.count()
        if esistenti and apply and not force:
            raise CommandError(
                f"PROD ha gia' {esistenti} visite: import rifiutato (usa --force per procedere comunque).")

        # Indici prod per nome (case-insensitive).
        tipi_prod = {t.nome.strip().lower(): t for t in TipoVisitaMedica.objects.all()}
        ruoli_prod = {r.nome.strip().lower(): r for r in RuoloOperativo.objects.all()}

        piano_tipi = []      # (nome, azione, ruoli_mappati, ruoli_saltati, ruoli_da_creare)
        for t in tipi_in:
            key = t["nome"].strip().lower()
            azione = "esiste" if key in tipi_prod else "CREA"
            mapp, salt, crea = [], [], []
            for rn in t.get("ruoli", []):
                rk = rn.strip().lower()
                if rk in ruoli_prod:
                    mapp.append(rn)
                elif crea_ruoli:
                    crea.append(rn)
                else:
                    salt.append(rn)
            piano_tipi.append((t["nome"], azione, mapp, salt, crea))

        tipi_da_creare = [p for p in piano_tipi if p[1] == "CREA"]
        ruoli_saltati = sorted({r for p in piano_tipi for r in p[3]})
        legacy_ids = sorted({v["legacy_anagrafica_id"] for v in visite_in})
        nomi_tipo_visite = {v["tipo_nome"].strip().lower() for v in visite_in}
        tipi_noti = set(tipi_prod) | {t["nome"].strip().lower() for t in tipi_in}
        visite_orfane = [n for n in nomi_tipo_visite if n not in tipi_noti]

        # ---- Report ----
        self.stdout.write("=== IMPORT VISITE (Fase 2) — %s ===" % ("APPLY" if apply else "DRY-RUN"))
        self.stdout.write(f"Tipi nel file: {len(tipi_in)} (di cui da creare: {len(tipi_da_creare)})")
        for nome, az, mapp, salt, crea in piano_tipi:
            extra = ""
            if mapp:  extra += f" | ruoli mappati: {', '.join(mapp)}"
            if crea:  extra += f" | ruoli DA CREARE: {', '.join(crea)}"
            if salt:  extra += f" | ruoli SALTATI (assenti in prod): {', '.join(salt)}"
            self.stdout.write(f"  [{az}] {nome}{extra}")
        if ruoli_saltati and not crea_ruoli:
            self.stdout.write(self.style.WARNING(
                "  Ruoli citati ma assenti in prod (saltati): " + ", ".join(ruoli_saltati)
                + "  — usa --crea-ruoli-mancanti se li vuoi creare."))
        self.stdout.write(f"Visite nel file: {len(visite_in)} | dipendenti distinti (legacy_id): {len(legacy_ids)}")
        if visite_orfane:
            self.stdout.write(self.style.ERROR(
                "  ATTENZIONE: alcune visite referenziano un tipo non risolvibile: " + ", ".join(visite_orfane)))

        if not apply:
            self.stdout.write(self.style.NOTICE("DRY-RUN: nulla scritto. Rilancia con --apply per eseguire."))
            return

        # ---- Apply (transazione) ----
        with transaction.atomic():
            for t in tipi_in:
                key = t["nome"].strip().lower()
                obj = tipi_prod.get(key)
                if obj is None:
                    obj = TipoVisitaMedica.objects.create(
                        nome=t["nome"], descrizione=t.get("descrizione", ""),
                        durata_mesi=t.get("durata_mesi", 12),
                        obbligatoria=t.get("obbligatoria", True),
                        is_active=t.get("is_active", True),
                    )
                    tipi_prod[key] = obj
                # M2M ruoli (solo esistenti; crea se richiesto)
                ruoli_obj = []
                for rn in t.get("ruoli", []):
                    rk = rn.strip().lower()
                    r = ruoli_prod.get(rk)
                    if r is None and crea_ruoli:
                        r = RuoloOperativo.objects.create(nome=rn)
                        ruoli_prod[rk] = r
                    if r is not None:
                        ruoli_obj.append(r)
                if ruoli_obj:
                    obj.ruoli_operativi.add(*ruoli_obj)

            creati = 0
            for v in visite_in:
                tk = v["tipo_nome"].strip().lower()
                tipo = tipi_prod.get(tk)
                if tipo is None:
                    continue  # gia' segnalata come orfana
                ds = v.get("data_svolgimento")
                if isinstance(ds, str):
                    ds = date.fromisoformat(ds)  # il save() del modello legge .month
                if ds is None:
                    continue  # data_svolgimento e' obbligatoria
                VisitaMedica.objects.create(
                    legacy_anagrafica_id=v["legacy_anagrafica_id"],
                    tipo=tipo,
                    data_svolgimento=ds,
                    esito=v.get("esito") or VisitaMedica.Esito.IDONEO,
                    prescrizioni=v.get("prescrizioni", ""),
                    medico_competente=v.get("medico_competente", ""),
                    note=v.get("note", ""),
                    referto_documento=None, created_by=None, updated_by=None,
                )  # data_scadenza ricalcolata in save() dal tipo
                creati += 1
        self.stdout.write(self.style.SUCCESS(f"FATTO: tipi totali ora {TipoVisitaMedica.objects.count()}, "
                                             f"visite create {creati}."))
