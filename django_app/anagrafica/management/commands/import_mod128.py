"""Management command: import_mod128

Importa il **MOD.128 MPQ** (Mansionario Processi Qualificati) dal PDF reale nei
modelli additivi ``models_mpq`` (ClienteQualificante, ProcessoQualificato,
AbilitazioneProcesso, CertificazioneIndividuale). Il PDF contiene **PII reale**
(nomi + numeri certificato): è letto **solo a runtime**, mai versionato.

Pipeline:
  1. estrae le tabelle dal PDF (PyMuPDF);
  2. interpreta ogni riga con il parser puro ``services.mod128_import``;
  3. **risolve le persone** per ``Cognome Nome`` sull'anagrafica legacy
     (``AnagraficaDipendente``) → ``legacy_anagrafica_id``; i non risolti sono
     elencati per mappatura manuale;
  4. **dry-run di default**: stampa il piano (cosa creerebbe + non risolti);
     con ``--apply`` scrive in modo **idempotente** (get_or_create per chiavi
     naturali) e registra ``MpqStorico`` (origine IMPORT).

Utilizzo:
    python manage.py import_mod128 --pdf "docs/anagrafica/MOD.128 ... Rev.16.pdf"
    python manage.py import_mod128 --pdf <path> --apply
"""
from __future__ import annotations

import glob

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from anagrafica.services import mod128_import as mi

_HEADER_TOKENS = {"cliente", "processo qualificato"}


def _estrai_righe(pdf_path: str):
    """Estrae le righe-dato (non header) dalle tabelle del PDF via PyMuPDF."""
    import fitz  # PyMuPDF

    righe = []
    doc = fitz.open(pdf_path)
    try:
        for page in doc:
            try:
                tabelle = page.find_tables()
            except Exception:
                continue
            for tab in tabelle.tables:
                for row in tab.extract():
                    cells = [(c or "").replace("\n", " ").strip() for c in row]
                    joined = " ".join(cells).lower()
                    if not any(cells):
                        continue
                    if "cliente" in joined and "processo qualificato" in joined:
                        continue  # header
                    righe.append(cells)
    finally:
        doc.close()
    return righe


def _riga_to_processo(cells: list[str]) -> dict | None:
    """Converte una riga (5 o 8 colonne) in un dict-processo strutturato."""
    n = len(cells)
    if n >= 8:
        cliente, processo, qualificato = cells[0], cells[1], cells[2]
        addetto, controllore, part145 = cells[3], cells[4], cells[5]
        scadenze, reparto = cells[6], cells[7]
    elif n >= 5:
        cliente, processo, qualificato = cells[0], cells[1], cells[2]
        addetto = controllore = part145 = ""
        scadenze, reparto = cells[3], cells[4]
    else:
        return None
    if not (cliente or processo):
        return None

    principale, addizionali = mi.split_clienti(cliente)
    scad = mi.parse_scadenza(scadenze)
    organizzativo = mi.is_organizzativo(qualificato)
    if organizzativo:
        persone = []
    else:
        persone = mi.allinea_ruoli(
            mi.split_personale(qualificato),
            addetto=addetto, controllore=controllore, part145=part145,
        )
    return {
        "cliente": principale or cliente.strip(),
        "clienti_addizionali": addizionali,
        "nome": (processo or "").strip()[:255],
        "regime": mi.infer_regime(principale or cliente, processo),
        "scad": scad,
        "reparti": mi.split_reparti(reparto),
        "organizzativo": organizzativo,
        "riferimento_dichiarazione": qualificato.strip()[:255] if organizzativo else "",
        "persone": persone,
    }


def _mappa_nomi_anagrafica() -> dict[str, int]:
    """{'cognome nome' | 'nome cognome' (casefold): legacy_id} per il match persone."""
    out: dict[str, int] = {}
    try:
        from core.legacy_models import AnagraficaDipendente
        for r in AnagraficaDipendente.objects.values("id", "cognome", "nome"):
            try:
                lid = int(r.get("id") or 0)
            except (TypeError, ValueError):
                continue
            cog = (r.get("cognome") or "").strip()
            nom = (r.get("nome") or "").strip()
            if not (cog or nom):
                continue
            out.setdefault(f"{cog} {nom}".casefold().strip(), lid)
            out.setdefault(f"{nom} {cog}".casefold().strip(), lid)
    except Exception:
        pass
    return out


class Command(BaseCommand):
    help = "Importa il MOD.128 MPQ dal PDF nei modelli models_mpq (dry-run di default)."

    def add_arguments(self, parser):
        parser.add_argument("--pdf", default="", help="Percorso del PDF MOD.128 (Rev.16).")
        parser.add_argument("--apply", action="store_true",
                            help="Scrive a DB (default: solo dry-run).")
        parser.add_argument("--esterni", nargs="*", default=None,
                            help="Nomi (Cognome Nome) da trattare come qualificatori "
                                 "esterni: creati come abilitazione esterna anziché saltati.")

    def handle(self, *args, **opts):
        pdf_path = opts.get("pdf") or ""
        if not pdf_path:
            cand = glob.glob("docs/anagrafica/MOD.128*.pdf")
            if not cand:
                raise CommandError("Specificare --pdf: nessun MOD.128*.pdf in docs/anagrafica/.")
            pdf_path = cand[0]

        righe = _estrai_righe(pdf_path)
        processi = [p for p in (_riga_to_processo(r) for r in righe) if p]
        nomi_map = _mappa_nomi_anagrafica()

        esterni = {e.casefold().strip() for e in (opts.get("esterni") or [])}

        # Risoluzione persone + statistiche.
        tot_ab = tot_certs = tot_org = tot_esterni = 0
        non_risolti: list[str] = []
        clienti = set()
        for p in processi:
            clienti.add(p["cliente"])
            clienti.update(p["clienti_addizionali"])
            if p["organizzativo"]:
                tot_org += 1
            for per in p["persone"]:
                tot_certs += len(per.get("certs") or [])
                key = per["nome"].casefold().strip()
                lid = nomi_map.get(key)
                if lid is not None:
                    per["legacy_id"], per["esterno"] = lid, False
                    tot_ab += 1
                elif key in esterni:
                    per["legacy_id"], per["esterno"] = 0, True
                    tot_ab += 1
                    tot_esterni += 1
                else:
                    per["legacy_id"], per["esterno"] = None, False
                    non_risolti.append(per["nome"])

        apply = bool(opts.get("apply"))
        self.stdout.write(f"PDF: {pdf_path}")
        self.stdout.write(
            f"{'[APPLY] ' if apply else '[DRY-RUN] '}"
            f"Processi: {len(processi)} · Clienti/enti: {len(clienti)} · "
            f"Abilitazioni risolte: {tot_ab} (di cui esterni: {tot_esterni}) · "
            f"Certificati: {tot_certs} · Processi organizzativi: {tot_org}"
        )
        if non_risolti:
            uniq = sorted(set(non_risolti))
            self.stdout.write(self.style.WARNING(
                f"Persone NON risolte in anagrafica ({len(uniq)}): " + "; ".join(uniq)
            ))

        if not apply:
            self.stdout.write("Nessuna scrittura (dry-run). Rilanciare con --apply per importare.")
            return

        creati = self._scrivi(processi)
        self.stdout.write(self.style.SUCCESS(
            "Import applicato: " + ", ".join(f"{k}={v}" for k, v in creati.items())
        ))

    @transaction.atomic
    def _scrivi(self, processi) -> dict:
        from anagrafica.models_mpq import (
            AbilitazioneProcesso, CertificazioneIndividuale,
            ClienteQualificante, MpqStorico, ProcessoQualificato,
        )
        from anagrafica.models import Reparto

        stats = {"clienti": 0, "processi": 0, "abilitazioni": 0, "certificazioni": 0}

        def _cliente(nome: str):
            nome = (nome or "").strip()
            if not nome:
                return None
            tipo = (ClienteQualificante.TIPO_ENTE_ACCREDITAMENTO
                    if nome.upper() == "NADCAP" else ClienteQualificante.TIPO_CLIENTE)
            obj, created = ClienteQualificante.objects.get_or_create(
                nome=nome, defaults={"tipo": tipo})
            stats["clienti"] += int(created)
            return obj

        for p in processi:
            cliente = _cliente(p["cliente"])
            if cliente is None:
                continue
            scad = p["scad"]
            proc, created = ProcessoQualificato.objects.get_or_create(
                cliente=cliente, nome=p["nome"],
                defaults={
                    "regime": p["regime"],
                    "tipo_validita": scad["tipo_validita"],
                    "data_scadenza": scad["data_scadenza"],
                    "durata_mesi": scad["durata_mesi"],
                    "stato": scad["stato"],
                    "motivo_stato": scad["motivo"],
                    "personale_modalita": (ProcessoQualificato.MODALITA_ORGANIZZATIVO
                                           if p["organizzativo"]
                                           else ProcessoQualificato.MODALITA_NOMINALE),
                    "riferimento_dichiarazione": p["riferimento_dichiarazione"],
                },
            )
            stats["processi"] += int(created)
            for nome_add in p["clienti_addizionali"]:
                c2 = _cliente(nome_add)
                if c2:
                    proc.clienti_addizionali.add(c2)
            for nome_rep in p["reparti"]:
                rep, _ = Reparto.objects.get_or_create(nome=nome_rep.strip())
                proc.reparti.add(rep)
            if created:
                MpqStorico.objects.create(
                    processo=proc, evento="Import MOD.128",
                    origine=MpqStorico.Origine.IMPORT,
                    dettaglio=f"Cliente {cliente.nome} · regime {p['regime']}",
                )

            for per in p["persone"]:
                lid = per.get("legacy_id")
                if lid is None:
                    continue
                ab, ab_created = AbilitazioneProcesso.objects.get_or_create(
                    legacy_anagrafica_id=lid,
                    nominativo_esterno=(per["nome"] if per.get("esterno") else ""),
                    processo=proc,
                    defaults={
                        "is_qualificato": per.get("is_qualificato", True),
                        "is_addetto": per.get("is_addetto", False),
                        "is_controllore": per.get("is_controllore", False),
                        "is_part145": per.get("is_part145", False),
                    },
                )
                stats["abilitazioni"] += int(ab_created)
                for cert in (per.get("certs") or []):
                    _, c_created = CertificazioneIndividuale.objects.get_or_create(
                        abilitazione=ab, schema=cert["schema"], numero=cert["numero"],
                        defaults={"data_scadenza": cert["data_scadenza"],
                                  "livello": cert.get("livello", "")},
                    )
                    stats["certificazioni"] += int(c_created)
        return stats
