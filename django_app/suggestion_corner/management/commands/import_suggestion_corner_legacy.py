"""Import dei record storici Suggestion Corner da export SharePoint (§7).

Legge un file JSON (lista di record) e crea le segnalazioni con `da_portale=False`
e `legacy_sharepoint_id` (import idempotente/incrementale). Reparti matchati per
nome, persone per email. Default **dry-run**: mostra il report senza scrivere;
`--apply` per applicare. Gli allegati di rete diventano `link_esterno`.

Schema record atteso (campi opzionali salvo `sharepoint_id`, `reparto_provenienza`,
`opportunity`):
{
  "sharepoint_id": 1,
  "data_segnalazione": "2024-03-15",
  "reparto_provenienza": "TORNI",
  "reparto_destinazione": "CNC",
  "processo": "Tornitura",
  "opportunity": "...",
  "autore_email": "mario@x.it",   # oppure "autore_username": "m.rossi"
  "anonima": false,
  "stato_sms": "SMS_SI",
  "plan_testo": "...", "incaricato_email": "...", "controllore_email": "...",
  # in alternativa alle email: "incaricato_username"/"controllore_username" (aliasusername)
  "do_testo": "...", "esito_do": "SI",
  "check_testo": "...", "esito_check": "POSITIVO|NEGATIVO|RINVIATO",
  "act_testo": "...",
  "allegati": ["\\\\novisrv\\..."],
  "stato": "CHIUSA"
}
"""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from anagrafica.models import AreaAziendale, Reparto
from suggestion_corner.models import (
    SuggestionCorner, SuggestionCornerAllegato, SuggestionCornerStorico,
)

User = get_user_model()

_STATI_VALIDI = {s.value for s in SuggestionCorner.Stato}


class Command(BaseCommand):
    help = "Importa i record storici Suggestion Corner da un export JSON SharePoint."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Percorso del file JSON.")
        parser.add_argument("--apply", action="store_true",
                            help="Applica le modifiche (default: dry-run).")
        parser.add_argument(
            "--reparto-map", default=None,
            help="Percorso di un JSON {nome_csv: nome_catalogo} per rimappare i "
                 "nomi reparto (provenienza/destinazione) prima del match. "
                 "Valore vuoto/null = ignora quel reparto (diventa nessun reparto).")

    def handle(self, *args, **opts):
        path = opts["file"]
        apply = opts["apply"]
        try:
            with open(path, encoding="utf-8") as fh:
                records = json.load(fh)
        except Exception as exc:
            raise CommandError(f"Impossibile leggere {path}: {exc}")
        if not isinstance(records, list):
            raise CommandError("Il file JSON deve contenere una lista di record.")

        # Rimappatura opzionale nomi reparto CSV→catalogo (chiavi case-insensitive).
        self.reparto_map = {}
        if opts.get("reparto_map"):
            try:
                with open(opts["reparto_map"], encoding="utf-8") as fh:
                    raw = json.load(fh)
            except Exception as exc:
                raise CommandError(f"Impossibile leggere la mappa reparti: {exc}")
            if not isinstance(raw, dict):
                raise CommandError("La mappa reparti deve essere un oggetto JSON.")
            self.reparto_map = {str(k).strip().lower(): (v or "") for k, v in raw.items()}

        rep = {"creati": 0, "aggiornati": 0, "saltati": 0,
               "reparti_mancanti": set(), "unita_non_risolte": set(),
               "persone_mancanti": set(), "errori": []}

        # Cache unità per nome (case-insensitive): Reparto e Area Aziendale.
        reparti = {r.nome.strip().lower(): r for r in Reparto.objects.all()}
        aree = {a.nome.strip().lower(): a for a in AreaAziendale.objects.select_related("reparto").all()}
        self._reparti = reparti
        self._aree = aree

        for rec in records:
            try:
                with transaction.atomic():
                    self._import_one(rec, rep)
                    if not apply:
                        transaction.set_rollback(True)
            except Exception as exc:
                rep["errori"].append(f"SP#{rec.get('sharepoint_id')}: {exc}")

        self._print_report(rep, apply)
        return None

    def _map_reparto(self, nome):
        """Applica la mappa `--reparto-map` (case-insensitive) al nome reparto.
        Se il nome non è mappato resta invariato; se è mappato a vuoto/null
        diventa stringa vuota (nessun reparto)."""
        nome = str(nome or "").strip()
        mapped = getattr(self, "reparto_map", {}).get(nome.lower())
        return nome if mapped is None else str(mapped).strip()

    def _persona(self, rec, prefix, rep):
        """Risolve una persona dal record: prima per `{prefix}_email`, poi per
        `{prefix}_username` (fonte unica username del portale = aliasusername)."""
        email = str(rec.get(f"{prefix}_email") or "").strip()
        if email:
            u = User.objects.filter(email__iexact=email).first()
            if u is not None:
                return u
        username = str(rec.get(f"{prefix}_username") or "").strip()
        if username:
            u = User.objects.filter(username__iexact=username).first()
            if u is not None:
                return u
        ident = email or username
        if ident:
            rep["persone_mancanti"].add(ident)
        return None

    def _unita(self, nome, rep):
        """Risolve un nome (dopo `--reparto-map`) in `(reparto, area)`.

        Prova prima il catalogo `Reparto`, poi `AreaAziendale` (restituendo anche
        il reparto padre dell'area). Se il nome non è vuoto ma non matcha nessuno
        dei due, lo registra in `unita_non_risolte` e ritorna `(None, None)` —
        i jolli storici (Altro/Generico) entrano così senza essere scartati.
        """
        nome = self._map_reparto(nome)
        if not nome:
            return None, None
        key = nome.lower()
        reparto = self._reparti.get(key)
        if reparto is not None:
            return reparto, None
        area = self._aree.get(key)
        if area is not None:
            return area.reparto, area  # reparto padre (può essere None) + area
        rep["unita_non_risolte"].add(nome)
        return None, None

    def _import_one(self, rec, rep):
        sp_id = rec.get("sharepoint_id")
        if sp_id is None:
            raise ValueError("sharepoint_id mancante")

        if SuggestionCorner.objects.filter(legacy_sharepoint_id=sp_id).exists():
            rep["saltati"] += 1
            return

        reparto, area_prov = self._unita(rec.get("reparto_provenienza", ""), rep)
        reparto_dest, area_dest = self._unita(rec.get("reparto_destinazione", ""), rep)
        anonima = bool(rec.get("anonima", False))
        autore = None if anonima else self._persona(rec, "autore", rep)

        seg = SuggestionCorner(
            legacy_sharepoint_id=sp_id,
            da_portale=False,
            anonima=anonima,
            reparto_provenienza=reparto,
            area_provenienza=area_prov,
            reparto_destinazione=reparto_dest,
            area_destinazione=area_dest,
            processo_libero=str(rec.get("processo", "")),
            opportunity=str(rec.get("opportunity", "")),
            stato_sms=rec.get("stato_sms") or SuggestionCorner.StatoSMS.DA_GESTIRE,
            plan_testo=str(rec.get("plan_testo", "")),
            incaricato=self._persona(rec, "incaricato", rep),
            controllore=self._persona(rec, "controllore", rep),
            do_testo=str(rec.get("do_testo", "")),
            esito_do=rec.get("esito_do", ""),
            check_testo=str(rec.get("check_testo", "")),
            esito_check=rec.get("esito_check", ""),  # gestisce anche RINVIATO
            act_testo=str(rec.get("act_testo", "")),
            created_by=autore,
        )
        if rec.get("data_segnalazione"):
            seg.data_segnalazione = rec["data_segnalazione"]
        seg.save()

        # Stato finale: .update() bypassa il descrittore FSM protetto.
        stato = rec.get("stato", "CHIUSA")
        if stato in _STATI_VALIDI:
            SuggestionCorner.objects.filter(pk=seg.pk).update(stato=stato)

        # Storico single-entry
        SuggestionCornerStorico.objects.create(
            segnalazione=seg, stato_precedente="", stato_nuovo=stato,
            campo_modificato="import", valore_nuovo="Importato da SharePoint",
        )

        # Allegati di rete → link_esterno
        for path in rec.get("allegati", []) or []:
            SuggestionCornerAllegato.objects.create(segnalazione=seg, link_esterno=str(path))

        rep["creati"] += 1

    def _print_report(self, rep, apply):
        mode = "APPLICATO" if apply else "DRY-RUN (nessuna scrittura)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"Import Suggestion Corner — {mode}"))
        self.stdout.write(f"  Creati:     {rep['creati']}")
        self.stdout.write(f"  Saltati (già presenti): {rep['saltati']}")
        if rep["unita_non_risolte"]:
            self.stdout.write(self.style.WARNING(
                f"  Unità (reparto/area) non risolte → provenienza vuota: "
                f"{sorted(rep['unita_non_risolte'])}"))
        if rep["reparti_mancanti"]:
            self.stdout.write(self.style.WARNING(
                f"  Reparti non trovati: {sorted(rep['reparti_mancanti'])}"))
        if rep["persone_mancanti"]:
            self.stdout.write(self.style.WARNING(
                f"  Persone (email) non trovate: {sorted(rep['persone_mancanti'])}"))
        for e in rep["errori"]:
            self.stdout.write(self.style.ERROR(f"  ERRORE {e}"))
