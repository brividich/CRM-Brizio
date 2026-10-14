from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook

from assets.models import Asset, AssetEndpoint, AssetFieldHistory, AssetITDetails
from assets.services.storico_asset import traccia

from .import_assets_excel import (
    _build_alias_map,
    _canonical_from_header,
    _clean_str,
    _compact,
    _detect_header_row,
    _is_blank,
    _iter_header_cells,
    _map_asset_type,
    _parse_int,
    _resolve_requested_sheets,
    _to_bool,
)

# Fogli IT dell'inventario. Telefonia, Carte B1 (password) e MASS-STORAGE restano fuori.
FOGLI_DEFAULT = "Management,Trust,Segmentation,WIRED-OSPITI,TVCC"

# Campo canonico Excel -> (tabella, attributo, lunghezza massima)
CAMPI_ASSET = {"reparto": ("reparto", 120), "manufacturer": ("manufacturer", 120), "model": ("model", 120),
               "serial": ("serial_number", 120)}
CAMPI_ENDPOINT = {"switch_port": ("switch_port", 120), "punto": ("punto", 120), "switch_name": ("switch_name", 120)}
CAMPI_IT_TESTO = {"os": "os", "cpu": "cpu", "ram": "ram", "disco": "disco"}
CAMPI_IT_BOOL = {"domain": "domain_joined", "edpr": "edr_enabled", "ad360": "ad360_managed",
                 "office_2fa": "office_2fa_enabled"}


SERIALI_NON_VALIDI = {"VM", "CLUSTER", "NA", "ND", "NO", "SI", "SN"}


def _pulisci(valore) -> str:
    """Testo pulito: spazi non separabili e doppi spazi ridotti a uno."""
    return " ".join(_clean_str(valore).split())


def _seriale_valido(nuovo: str, attuale) -> bool:
    """Scarta valori che non sono seriali (VM, CLUSTER...) e varianti con suffisso -1/-2 gia' in prod."""
    if len(nuovo) < 5 or not any(c.isdigit() for c in nuovo) or _compact(nuovo) in SERIALI_NON_VALIDI:
        return False
    attuale = (attuale or "").strip()
    if attuale and attuale != nuovo and attuale.startswith(nuovo) and attuale[len(nuovo):len(nuovo) + 1] in "-_/":
        return False
    return True


# VLAN -> prefisso della rete (l'Excel riporta solo l'ultimo numero dell'IP).
PREFISSO_VLAN = {1: "10.0.0", 1010: "10.10.10", 13: "172.16.13", 23: "192.168.23", 24: "192.168.24", 98: "192.168.98"}


def _vlan(valore):
    """VLAN come intero; '1010/1' -> 1010."""
    return _parse_int(_clean_str(valore).split("/")[0])


def _ip_completo(valore, vlan) -> str:
    """Ultimo ottetto + VLAN -> IP completo; 'DHCP' o IP gia' completi restano com'e'."""
    testo = _clean_str(valore)
    if testo.isdigit() and vlan in PREFISSO_VLAN:
        return f"{PREFISSO_VLAN[vlan]}.{testo}"
    return testo


def _prefisso_ip(nome_foglio: str) -> str:
    """'Management 172.16.13.x' -> '172.16.13.'; vuoto se il titolo non ha un solo prefisso."""
    trovati = re.findall(r"(\d{1,3}\.\d{1,3}\.\d{1,3})\.[xX]", nome_foglio)
    return f"{trovati[0]}." if len(trovati) == 1 else ""


class Command(BaseCommand):
    help = (
        "Riallinea gli asset GIA' PRESENTI al foglio Excel dell'inventario IT (match per nome PC, poi IP; mai per seriale). "
        "Non crea asset, non tocca nome/IP/stato; i valori diversi vengono SOVRASCRITTI con quelli dell'Excel. "
        "Default dry-run: serve --apply per scrivere. Password/PIN/PUK non vengono mai letti."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Percorso del file Excel.")
        parser.add_argument("--sheets", default=FOGLI_DEFAULT, help="Fogli separati da virgola (match parziale).")
        parser.add_argument("--apply", action="store_true", help="Scrive su DB (senza: solo simulazione).")
        parser.add_argument("--report", default="", help="CSV con una riga per ogni campo modificato / riga non agganciata.")
        parser.add_argument("--utente-id", type=int, default=None, help="Autore nello storico asset.")

    def handle(self, *args, **opts):
        percorso = Path(opts["file"])
        if not percorso.exists():
            raise CommandError(f"File non trovato: {percorso}")
        apply = bool(opts["apply"])
        from django.contrib.auth import get_user_model

        utente = get_user_model().objects.filter(pk=opts["utente_id"]).first() if opts["utente_id"] else None
        wb = load_workbook(str(percorso), data_only=True, read_only=False)
        fogli, mancanti = _resolve_requested_sheets(wb.sheetnames, opts["sheets"], False, False)
        if mancanti:
            self.stdout.write(self.style.WARNING("Fogli non trovati: " + ", ".join(mancanti)))

        alias = _build_alias_map()
        per_nome = defaultdict(list)
        for a in Asset.objects.all().only("id", "name", "serial_number"):
            per_nome[_compact(a.name)].append(a.id)
        for ep in AssetEndpoint.objects.exclude(endpoint_name="").only("asset_id", "endpoint_name"):
            if ep.asset_id not in per_nome[_compact(ep.endpoint_name)]:
                per_nome[_compact(ep.endpoint_name)].append(ep.asset_id)
        per_ip = defaultdict(list)
        for ep in AssetEndpoint.objects.exclude(ip__isnull=True).exclude(ip="").only("asset_id", "ip"):
            per_ip[ep.ip.strip()].append(ep.asset_id)

        righe_report: list[list] = []
        stat = defaultdict(int)

        for nome_foglio in fogli:
            ws = wb[nome_foglio]
            riga_h = _detect_header_row(ws, alias)
            intest = _iter_header_cells(ws, riga_h)
            canon = {col: _canonical_from_header(lbl, alias) for col, lbl in intest.items()}
            prefisso = _prefisso_ip(nome_foglio)
            self.stdout.write(f"[{nome_foglio}] header riga {riga_h}")
            for r in range(riga_h + 1, (ws.max_row or riga_h) + 1):
                v: dict = {}
                for col, chiave in canon.items():
                    if chiave and (chiave not in v or _is_blank(v[chiave])):
                        v[chiave] = ws.cell(row=r, column=col).value
                nome = _clean_str(v.get("name"))
                seriale = _clean_str(v.get("serial"))
                ip_raw = _clean_str(v.get("ip"))
                if not (nome or seriale or ip_raw):
                    continue
                stat["righe"] += 1

                candidati = list(dict.fromkeys(per_nome.get(_compact(nome), []))) if nome else []
                via = "nome"
                if not candidati and ip_raw.isdigit() and prefisso:
                    candidati = list(dict.fromkeys(per_ip.get(prefisso + ip_raw, [])))
                    via = "ip"
                if len(candidati) != 1:
                    esito = "NON TROVATO" if not candidati else f"AMBIGUO ({len(candidati)} asset)"
                    stat["non_agganciate" if not candidati else "ambigue"] += 1
                    righe_report.append([nome_foglio, r, nome, ip_raw, seriale, esito, "", "", ""])
                    continue

                modifiche = self._applica(candidati[0], v, nome_foglio, r, apply, utente, via)
                for campo, vecchio, nuovo in modifiche:
                    righe_report.append([nome_foglio, r, nome, ip_raw, seriale, f"MODIFICA via {via}", campo, vecchio, nuovo])
                stat["asset_modificati" if modifiche else "asset_invariati"] += 1
                stat["campi_modificati"] += len(modifiche)

        if opts["report"]:
            with open(opts["report"], "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(["foglio", "riga", "nome", "ip", "seriale", "esito", "campo", "prima", "dopo"])
                w.writerows(righe_report)
            self.stdout.write(f"Report: {opts['report']}")

        self.stdout.write(self.style.SUCCESS(
            f"{'APPLICATO' if apply else 'DRY-RUN'} | righe={stat['righe']} "
            f"asset modificati={stat['asset_modificati']} invariati={stat['asset_invariati']} "
            f"campi modificati={stat['campi_modificati']} non trovati={stat['non_agganciate']} ambigui={stat['ambigue']}"
        ))
        if not apply:
            self.stdout.write(self.style.WARNING("DRY-RUN: nessuna scrittura. Rilancia con --apply."))

    def _applica(self, asset_id, v, foglio, riga, apply, utente, via):
        """Calcola (e se apply scrive) i campi diversi; ritorna [(campo, prima, dopo)]."""
        modifiche: list[tuple[str, str, str]] = []
        with transaction.atomic():
            with traccia([asset_id], fonte=AssetFieldHistory.FONTE_IMPORT, utente=utente,
                         dettaglio=f"Riallineamento da Excel {foglio} riga {riga}") if apply else _Nulla():
                asset = Asset.objects.get(pk=asset_id)
                da_salvare = []
                for chiave, (attr, lung) in CAMPI_ASSET.items():
                    nuovo = _pulisci(v.get(chiave))[:lung]
                    if chiave == "serial" and not _seriale_valido(nuovo, asset.serial_number):
                        continue
                    if nuovo and (getattr(asset, attr) or "") != nuovo:
                        modifiche.append((f"asset.{attr}", getattr(asset, attr) or "", nuovo))
                        setattr(asset, attr, nuovo)
                        da_salvare.append(attr)
                tipo = _clean_str(v.get("type"))
                if tipo:
                    mappato = _map_asset_type(tipo, foglio)
                    if mappato == Asset.TYPE_FIREWALL and _compact(tipo) not in {"FIREWALL", "FW"}:
                        mappato = Asset.TYPE_OTHER  # switch/router/AP non sono firewall
                    if mappato != Asset.TYPE_OTHER and asset.asset_type == Asset.TYPE_OTHER:
                        modifiche.append(("asset.asset_type", asset.asset_type, mappato))
                        asset.asset_type = mappato
                        da_salvare.append("asset_type")
                if da_salvare and apply:
                    asset.save(update_fields=da_salvare + ["updated_at"])

                vlan = _vlan(v.get("vlan"))
                ip = _ip_completo(v.get("ip"), vlan)[:80]
                ep = asset.endpoints.order_by("id").first()
                if ep is None:
                    campi = {"endpoint_name": (_pulisci(v.get("name")) or asset.name)[:255], "vlan": vlan,
                             "ip": ip or None,
                             **{a: _pulisci(v.get(k))[:l] for k, (a, l) in CAMPI_ENDPOINT.items()}}
                    if vlan is not None or ip or any(campi[a] for a in ("switch_name", "switch_port", "punto")):
                        modifiche.append(("endpoint.CREATO", "", " | ".join(
                            f"{k}={x}" for k, x in campi.items() if x not in (None, ""))))
                        if apply:
                            AssetEndpoint.objects.create(asset=asset, **campi)
                else:
                    if ip and not (ep.ip or "").strip():
                        modifiche.append(("endpoint.ip", "", ip))
                        ep.ip = ip
                        if apply:
                            ep.save(update_fields=["ip"])
                if ep is not None:
                    mod_ep = []
                    if vlan is not None and ep.vlan != vlan:
                        modifiche.append(("endpoint.vlan", str(ep.vlan or ""), str(vlan)))
                        ep.vlan = vlan
                        mod_ep.append("vlan")
                    for chiave, (attr, lung) in CAMPI_ENDPOINT.items():
                        nuovo = _pulisci(v.get(chiave))[:lung]
                        if nuovo and getattr(ep, attr) != nuovo:
                            modifiche.append((f"endpoint.{attr}", getattr(ep, attr), nuovo))
                            setattr(ep, attr, nuovo)
                            mod_ep.append(attr)
                    if mod_ep and apply:
                        try:
                            ep.save(update_fields=mod_ep)
                        except Exception as exc:  # vincolo univoco asset/nome/vlan/ip
                            modifiche.append(("endpoint.ERRORE", "", str(exc)[:120]))

                det = getattr(asset, "it_details", None)
                mod_it = []
                if det is None:
                    det = AssetITDetails(asset=asset)
                for chiave, attr in CAMPI_IT_TESTO.items():
                    nuovo = _clean_str(v.get(chiave))[:120]
                    if nuovo and getattr(det, attr) != nuovo:
                        modifiche.append((f"it.{attr}", getattr(det, attr), nuovo))
                        setattr(det, attr, nuovo)
                        mod_it.append(attr)
                for chiave, attr in CAMPI_IT_BOOL.items():
                    if _is_blank(v.get(chiave)):
                        continue
                    nuovo = _to_bool(v.get(chiave))
                    if getattr(det, attr) != nuovo:
                        modifiche.append((f"it.{attr}", str(getattr(det, attr)), str(nuovo)))
                        setattr(det, attr, nuovo)
                        mod_it.append(attr)
                # Solo la presenza della password BIOS (il valore non viene mai letto).
                if not _is_blank(v.get("bios_pwd")) and not det.bios_pwd_set:
                    modifiche.append(("it.bios_pwd_set", "False", "True"))
                    det.bios_pwd_set = True
                    mod_it.append("bios_pwd_set")
                if mod_it and apply:
                    det.save()
        return modifiche


class _Nulla:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
