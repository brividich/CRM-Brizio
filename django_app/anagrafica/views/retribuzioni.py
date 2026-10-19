"""Viste anagrafica — Retribuzioni, ratei, cedolini, contratti, tipologie e livelli.

Spacchettamento di ``anagrafica/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import calendar
import csv
import logging
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import (
    HttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
# Alias esplicito: in questo file `timezone` è già importato dentro varie
# funzioni (come `tz`/`_tz`) e `datetime.timezone` è un'altra cosa ancora.
from django.views.decorators.http import require_POST

from django.contrib.auth.decorators import login_required
from core import naming
from core.legacy_models import AnagraficaDipendente
from core.legacy_utils import get_legacy_user

from ..models import (
    DipendenteAnagraficaAziendale,
    DipendenteAnagraficaCivile,
    ImportazioneRetributiva,
    LivelloContrattuale,
    ImportazioneCedolini,
    SaldoCedolino,
    StoricoContratto,
    TipologiaContratto,
    VoceRetributiva,
    _classify_pay_item,
)


from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Voci retributive — importazione CSV dallo studio paghe
# ---------------------------------------------------------------------------

def _import_csv_retribuzioni(file_obj, user, file_nome: str = "") -> ImportazioneRetributiva:
    """Parsa il CSV paghe e crea ImportazioneRetributiva + VoceRetributiva."""
    raw = file_obj.read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Impossibile decodificare il file CSV (provati utf-8, latin-1, cp1252).")

    reader = csv.DictReader(StringIO(text), delimiter=";")
    rows = [r for r in reader if any(v.strip() for v in r.values())]
    if not rows:
        raise ValueError("Il file CSV è vuoto o non contiene righe valide.")

    # Data competenza dal primo record
    first_date_str = (rows[0].get("date") or "").strip()
    try:
        data_comp_raw = datetime.strptime(first_date_str, "%d/%m/%Y").date()
        data_competenza = data_comp_raw.replace(day=1)
    except ValueError:
        raise ValueError(f"Formato data non riconosciuto: '{first_date_str}' (atteso gg/mm/aaaa).")

    importazione = ImportazioneRetributiva.objects.create(
        data_competenza=data_competenza,
        importato_da=user,
        file_nome=file_nome,
        righe_totali=len(rows),
    )

    # Mappa codice fiscale → legacy_anagrafica_id
    all_cf = {(r.get("tax_code") or "").strip().upper() for r in rows if (r.get("tax_code") or "").strip()}
    cf_to_id: dict[str, int] = dict(
        DipendenteAnagraficaCivile.objects.filter(
            codice_fiscale__in=all_cf
        ).values_list("codice_fiscale", "legacy_anagrafica_id")
    )

    # Fallback nome "COGNOME NOME" → legacy_anagrafica_id quando il CF non è ancora in DipendenteAnagraficaCivile
    # Solo nomi unici di persone senza CF registrato: mai sull'omonimo.
    nome_to_id: dict[str, int] = {}
    try:
        from core.legacy_anagrafica import nomi_sicuri_per_abbinamento

        nome_to_id = nomi_sicuri_per_abbinamento()
    except Exception:
        logger.warning("Fallback nome-based per retribuzioni non disponibile (legacy DB non raggiungibile)")

    # Voci dell'ultima importazione precedente per rilevare variazioni
    prev_import = (
        ImportazioneRetributiva.objects
        .filter(data_competenza__lt=data_competenza)
        .order_by("-data_competenza")
        .first()
    )
    prev_voci: dict[tuple, Decimal] = {}
    if prev_import:
        for voce in VoceRetributiva.objects.filter(importazione=prev_import):
            prev_voci[(voce.tax_code, voce.pay_item_key)] = voce.importo

    ok = err = 0
    scarti: list[dict] = []
    voci_to_create: list[VoceRetributiva] = []
    for n_riga, row in enumerate(rows, start=2):
        try:
            tax_code = (row.get("tax_code") or "").strip().upper()
            pay_item = (row.get("pay_item") or "").strip()
            value_str = (row.get("value") or "0").strip().replace(",", ".")
            date_str = (row.get("date") or "").strip()
            if not tax_code or not pay_item:
                err += 1
                scarti.append({"riga": n_riga, "chiave": tax_code, "motivo": "Codice fiscale o voce mancante"})
                continue
            importo = Decimal(value_str)
            data_riga = datetime.strptime(date_str, "%d/%m/%Y").date()
            pay_item_key = pay_item.lower()
            categoria = _classify_pay_item(pay_item_key)
            legacy_id = cf_to_id.get(tax_code)
            if not legacy_id:
                nome_csv = (row.get("nome") or "").strip().upper()
                legacy_id = nome_to_id.get(nome_csv)
            prev_importo = prev_voci.get((tax_code, pay_item_key))
            is_changed = prev_importo is not None and prev_importo != importo
            voci_to_create.append(VoceRetributiva(
                importazione=importazione,
                tax_code=tax_code,
                legacy_anagrafica_id=legacy_id,
                data_competenza=data_riga,
                pay_item=pay_item,
                pay_item_key=pay_item_key,
                categoria=categoria,
                importo=importo,
                is_changed=is_changed,
                importo_precedente=prev_importo if is_changed else None,
            ))
            ok += 1
        except (InvalidOperation, ValueError):
            err += 1
            scarti.append({"riga": n_riga, "chiave": tax_code, "motivo": "Importo o data non validi"})

    VoceRetributiva.objects.bulk_create(voci_to_create)
    importazione.righe_ok = ok
    importazione.righe_errore = err
    importazione.scarti = scarti[:2000]
    importazione.save(update_fields=["righe_ok", "righe_errore", "scarti"])
    return importazione


def _ritorno_import(request, pagina: str, fallback: str):
    """Dove torna un import di Amministrazione: la pagina che lo incorpora.

    Da ottobre 2026 gli import non hanno più una pagina propria: vivono nella
    sezione «Importazione» di Cedolini (retribuzioni) e di Ferie e permessi
    (cedolini). Quelle pagine chiedono il permesso HR; un amministratore senza
    HR resta sulla pagina di import di prima, che continua a funzionare.
    """
    if _helpers._check_hr_permission(request):
        return redirect(f"{reverse(pagina)}#importazione")
    return redirect(fallback)


@login_required
def retribuzioni_import(request):
    """Pagina importazione CSV retributivo (solo admin)."""
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    if not is_admin:
        messages.error(request, "Accesso riservato agli amministratori.")
        return redirect("anagrafica:dipendenti_list")

    if request.method == "POST":
        file_obj = request.FILES.get("file_csv")
        if not file_obj:
            messages.error(request, "Nessun file selezionato.")
        else:
            try:
                imp = _import_csv_retribuzioni(file_obj, request.user, file_obj.name)
                messages.success(
                    request,
                    f"Importazione completata: {imp.righe_ok} voci caricate"
                    f"{f', {imp.righe_errore} errori' if imp.righe_errore else ''}."
                )
            except Exception as exc:
                logger.exception("Errore importazione CSV retribuzioni")
                messages.error(request, f"Errore durante l'importazione: {exc}")
        return _ritorno_import(request, "anagrafica:retribuzioni_globale", "anagrafica:retribuzioni_import")
    if _helpers._check_hr_permission(request):
        return redirect(f"{reverse('anagrafica:retribuzioni_globale')}#importazione")

    importazioni = list(
        ImportazioneRetributiva.objects
        .filter(origine=ImportazioneRetributiva.ORIGINE_CSV)
        .select_related("importato_da")[:30]
    )
    return render(request, "anagrafica/pages/retribuzioni_import.html", {
        "importazioni": importazioni,
        "is_admin": is_admin,
    })


# ---------------------------------------------------------------------------
# Storico contrattuale — import CSV + CRUD manuale
# ---------------------------------------------------------------------------

_CONTRATTO_LABEL_MAP: dict[str, str] = {
    label.lower(): value
    for value, label in DipendenteAnagraficaAziendale.CONTRATTO_CHOICES
}


def _normalize_contratto_choice(raw: str) -> str:
    key = raw.strip().lower()
    if key in _CONTRATTO_LABEL_MAP:
        return _CONTRATTO_LABEL_MAP[key]
    # partial match
    for k, v in _CONTRATTO_LABEL_MAP.items():
        if k in key or key in k:
            return v
    return ""


def _import_csv_contratti(file_obj, user) -> tuple[int, int, int]:
    """Parsa il CSV contrattuale e crea/aggiorna record StoricoContratto.

    Formato: Codice fiscale;Data Inizio;Data Fine;Tipo di contratto;Qualifica;Livello;CCNL;Descrizione livello
    Più righe con stesso (CF, Data Inizio, Data Fine) vengono aggregate automaticamente.
    Restituisce (created, updated, skipped).
    """
    raw = file_obj.read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Impossibile decodificare il file CSV (provati utf-8, latin-1, cp1252).")

    # Mappa CF → legacy_id
    cf_to_id: dict[str, int] = {}
    for row in DipendenteAnagraficaCivile.objects.filter(
        codice_fiscale__isnull=False, legacy_anagrafica_id__isnull=False
    ).exclude(codice_fiscale="").values("codice_fiscale", "legacy_anagrafica_id"):
        cf_to_id[str(row["codice_fiscale"]).strip().upper()] = row["legacy_anagrafica_id"]

    # Fallback nome-based
    # Solo nomi unici di persone senza CF registrato: mai sull'omonimo.
    nome_to_id: dict[str, int] = {}
    try:
        from core.legacy_anagrafica import nomi_sicuri_per_abbinamento

        nome_to_id = nomi_sicuri_per_abbinamento()
    except Exception:
        logger.warning("Fallback nome-based per contratti non disponibile")

    # Raggruppa righe per (CF, data_inizio, data_fine)
    groups: dict[tuple, dict] = {}
    reader = csv.DictReader(StringIO(text), delimiter=";")
    for row in reader:
        cf = (row.get("Codice fiscale") or "").strip().upper()
        if not cf:
            continue
        di_raw = (row.get("Data Inizio") or "").strip()
        df_raw = (row.get("Data Fine") or "").strip()
        if not di_raw:
            continue
        try:
            di = datetime.strptime(di_raw, "%d/%m/%Y").date()
            df = datetime.strptime(df_raw, "%d/%m/%Y").date() if df_raw else None
        except ValueError:
            continue
        key = (cf, di, df)
        if key not in groups:
            groups[key] = {
                "tax_code": cf, "data_inizio": di, "data_fine": df,
                "tipologia_contratto": "", "qualifica_nome": "",
                "codice_livello": "", "ccnl": "", "descrizione_livello": "",
            }
        g = groups[key]
        tipo = (row.get("Tipo di contratto") or "").strip()
        qualifica = (row.get("Qualifica") or "").strip()
        livello = (row.get("Livello") or "").strip()
        ccnl = (row.get("CCNL") or "").strip()
        desc = (row.get("Descrizione livello") or "").strip()
        if tipo and not g["tipologia_contratto"]:
            g["tipologia_contratto"] = _normalize_contratto_choice(tipo)
        if qualifica and not g["qualifica_nome"]:
            g["qualifica_nome"] = qualifica
        if livello and not g["codice_livello"]:
            g["codice_livello"] = livello.upper()
        if ccnl and not g["ccnl"]:
            g["ccnl"] = ccnl
        if desc and not g["descrizione_livello"]:
            g["descrizione_livello"] = desc

    created_n = updated_n = 0
    for (cf, di, df), data in groups.items():
        lid = cf_to_id.get(cf) or nome_to_id.get(cf)
        defaults = {
            "tipologia_contratto": data["tipologia_contratto"],
            "qualifica_nome": data["qualifica_nome"],
            "codice_livello": data["codice_livello"],
            "ccnl": data["ccnl"],
            "descrizione_livello": data["descrizione_livello"],
            "legacy_anagrafica_id": lid,
            "importato_da": user,
        }
        _, created = StoricoContratto.objects.update_or_create(
            tax_code=cf, data_inizio=di, data_fine=df,
            defaults=defaults,
        )
        if created:
            created_n += 1
        else:
            updated_n += 1
    return created_n, updated_n, 0


@login_required
def contratti_import(request):
    """Pagina importazione CSV contratti (solo admin)."""
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    if not is_admin:
        messages.error(request, "Accesso riservato agli amministratori.")
        return redirect("anagrafica:dipendenti_list")

    stats = None
    if request.method == "POST":
        file_obj = request.FILES.get("file_csv")
        if not file_obj:
            messages.error(request, "Nessun file selezionato.")
        else:
            try:
                created, updated, _ = _import_csv_contratti(file_obj, request.user)
                messages.success(
                    request,
                    f"Importazione completata: {created} record creati, {updated} aggiornati.",
                )
                stats = {"created": created, "updated": updated}
                return redirect("anagrafica:contratti_import")
            except Exception as exc:
                logger.exception("Errore importazione CSV contratti")
                messages.error(request, f"Errore durante l'importazione: {exc}")

    recenti = list(
        StoricoContratto.objects.select_related("importato_da").order_by("-created_at")[:30]
    )
    return render(request, "anagrafica/pages/contratti_import.html", {
        "recenti": recenti,
        "is_admin": is_admin,
    })


# ---------------------------------------------------------------------------
# Livelli contrattuali — catalogo (CRUD)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def livello_contrattuale_create(request):
    ok, resp = _helpers._impostazioni_admin_check(request, "livelli")
    if not ok:
        return resp

    codice = (request.POST.get("codice") or "").strip().upper()[:10]
    if not codice:
        messages.error(request, "Il codice del livello è obbligatorio.")
        return _helpers._redirect_impostazioni("livelli")

    descrizione = (request.POST.get("descrizione") or "").strip()[:200]
    try:
        ordine = max(0, int(request.POST.get("ordine") or "0"))
    except ValueError:
        ordine = 0

    _, created = LivelloContrattuale.objects.get_or_create(
        codice=codice,
        defaults={"descrizione": descrizione, "ordine": ordine},
    )
    if created:
        messages.success(request, f'Livello "{codice}" creato.')
    else:
        messages.warning(request, f'Esiste già un livello con codice "{codice}".')
    return _helpers._redirect_impostazioni("livelli")


@login_required
@require_POST
def livello_contrattuale_edit(request, livello_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "livelli")
    if not ok:
        return resp

    livello = get_object_or_404(LivelloContrattuale, pk=livello_id)
    codice = (request.POST.get("codice") or "").strip().upper()[:10]
    if not codice:
        messages.error(request, "Il codice del livello è obbligatorio.")
        return _helpers._redirect_impostazioni("livelli")

    try:
        ordine = max(0, int(request.POST.get("ordine") or "0"))
    except ValueError:
        ordine = 0

    livello.codice = codice
    livello.descrizione = (request.POST.get("descrizione") or "").strip()[:200]
    livello.ordine = ordine
    livello.is_active = request.POST.get("is_active") == "1"
    livello.save()
    messages.success(request, f'Livello "{livello.codice}" aggiornato.')
    return _helpers._redirect_impostazioni("livelli")


@login_required
@require_POST
def livello_contrattuale_delete(request, livello_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "livelli")
    if not ok:
        return resp

    livello = get_object_or_404(LivelloContrattuale, pk=livello_id)
    codice = livello.codice
    # Controllo se esistono StoricoContratto con questo codice
    if StoricoContratto.objects.filter(codice_livello=codice).exists():
        messages.error(
            request,
            f'"{codice}" è referenziato nello storico contrattuale — non eliminabile. Disattivalo.',
        )
        return _helpers._redirect_impostazioni("livelli")

    livello.delete()
    messages.success(request, f'Livello "{codice}" eliminato.')
    return _helpers._redirect_impostazioni("livelli")


# ---------------------------------------------------------------------------
# Tipologie contratto — catalogo (CRUD)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def tipologia_contratto_create(request):
    ok, resp = _helpers._impostazioni_admin_check(request, "tipologie")
    if not ok:
        return resp

    codice = (request.POST.get("codice") or "").strip().upper()[:20]
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not codice or not nome:
        messages.error(request, "Codice e nome della tipologia sono obbligatori.")
        return _helpers._redirect_impostazioni("tipologie")

    try:
        ordine = max(0, int(request.POST.get("ordine") or "0"))
    except ValueError:
        ordine = 0

    _, created = TipologiaContratto.objects.get_or_create(
        codice=codice,
        defaults={"nome": nome, "ordine": ordine},
    )
    if created:
        messages.success(request, f'Tipologia "{codice}" creata.')
    else:
        messages.warning(request, f'Esiste già una tipologia con codice "{codice}".')
    return _helpers._redirect_impostazioni("tipologie")


@login_required
@require_POST
def tipologia_contratto_edit(request, tipologia_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "tipologie")
    if not ok:
        return resp

    tipologia = get_object_or_404(TipologiaContratto, pk=tipologia_id)
    codice = (request.POST.get("codice") or "").strip().upper()[:20]
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not codice or not nome:
        messages.error(request, "Codice e nome della tipologia sono obbligatori.")
        return _helpers._redirect_impostazioni("tipologie")

    try:
        ordine = max(0, int(request.POST.get("ordine") or "0"))
    except ValueError:
        ordine = 0

    tipologia.codice = codice
    tipologia.nome = nome
    tipologia.ordine = ordine
    tipologia.is_active = request.POST.get("is_active") == "1"
    tipologia.save()
    messages.success(request, f'Tipologia "{tipologia.codice}" aggiornata.')
    return _helpers._redirect_impostazioni("tipologie")


@login_required
@require_POST
def tipologia_contratto_delete(request, tipologia_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "tipologie")
    if not ok:
        return resp

    tipologia = get_object_or_404(TipologiaContratto, pk=tipologia_id)
    codice = tipologia.codice
    if StoricoContratto.objects.filter(tipologia_contratto=codice).exists():
        messages.error(
            request,
            f'"{codice}" è referenziata nello storico contrattuale — non eliminabile. Disattivala.',
        )
        return _helpers._redirect_impostazioni("tipologie")

    tipologia.delete()
    messages.success(request, f'Tipologia "{codice}" eliminata.')
    return _helpers._redirect_impostazioni("tipologie")


# Cedolini — import XLSX via pagina web (replica logica del management command)
# ---------------------------------------------------------------------------

_MESI_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

_COL_CF       = 0
_COL_MESE     = 3
_COL_ANNO     = 4
_COL_DATA_PER = 5
_COL_ANZ_ANNI = 8
_COL_ANZ_MESI = 9
_COL_FERIE_AP  = 16
_COL_FERIE_MAT = 17
_COL_FERIE_GOD = 18
_COL_FERIE_RES = 19
_COL_PERM_AP   = 20
_COL_PERM_MAT  = 21
_COL_PERM_GOD  = 22
_COL_PERM_RES  = 23
_COL_ROL_AP    = 24
_COL_ROL_MAT   = 25
_COL_ROL_GOD   = 26
_COL_ROL_RES   = 27
_COL_EXFEST_AP  = 28
_COL_EXFEST_MAT = 29
_COL_EXFEST_GOD = 30
_COL_EXFEST_RES = 31


def _ced_dec(val) -> Decimal:
    if val is None:
        return Decimal("0")
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _ced_int(val):
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _ced_data_competenza(row) -> "date | None":
    dt = row[_COL_DATA_PER]
    if isinstance(dt, datetime):
        return dt.date()
    if isinstance(dt, date):
        return dt
    mese_str = str(row[_COL_MESE] or "").strip().lower()
    anno = _ced_int(row[_COL_ANNO])
    mese_num = _MESI_IT.get(mese_str)
    if mese_num and anno:
        ultimo = calendar.monthrange(anno, mese_num)[1]
        return date(anno, mese_num, ultimo)
    return None


def _import_xlsx_cedolini(file_obj, user, file_nome: str) -> ImportazioneCedolini:
    """Importa saldi cedolini da file XLSX e crea record su DB."""
    try:
        import openpyxl
    except ImportError as exc:
        raise ValueError("openpyxl non installato sul server.") from exc

    wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
    foglio = "Dati"
    if foglio not in wb.sheetnames:
        raise ValueError(
            f"Foglio '{foglio}' non trovato nel file. Fogli disponibili: {', '.join(wb.sheetnames)}"
        )
    ws = wb[foglio]

    cf_to_lid = dict(
        DipendenteAnagraficaCivile.objects
        .exclude(codice_fiscale="")
        .values_list("codice_fiscale", "legacy_anagrafica_id")
    )

    periodi: dict = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        cf = str(row[_COL_CF] or "").strip().upper()
        if not cf:
            continue
        dt = _ced_data_competenza(row)
        if dt is None:
            continue
        periodi.setdefault(dt, []).append((cf, row))

    if not periodi:
        raise ValueError("Il file non contiene righe valide (nessun codice fiscale o data competenza leggibili).")

    totale_ok = totale_err = totale_nf = 0
    ultima_imp = None

    with transaction.atomic():
        for dt in sorted(periodi):
            righe = periodi[dt]
            imp = ImportazioneCedolini.objects.create(
                data_competenza=dt,
                origine=ImportazioneCedolini.ORIGINE_XLSX,
                importato_da=user,
                file_nome=file_nome,
                righe_totali=len(righe),
            )
            ok = err = nf = 0
            scarti: list[dict] = []
            for n_riga, (cf, row) in enumerate(righe, start=2):
                try:
                    lid = cf_to_lid.get(cf)
                    if lid is None:
                        nf += 1
                        scarti.append({"riga": n_riga, "chiave": cf, "motivo": "Codice fiscale non in anagrafica (saldo importato senza scheda)"})
                    SaldoCedolino.objects.update_or_create(
                        tax_code=cf,
                        data_competenza=dt,
                        defaults=dict(
                            importazione=imp,
                            legacy_anagrafica_id=lid,
                            anzianita_anni=_ced_int(row[_COL_ANZ_ANNI]),
                            anzianita_mesi=_ced_int(row[_COL_ANZ_MESI]),
                            ferie_anni_prec=_ced_dec(row[_COL_FERIE_AP]),
                            ferie_maturati=_ced_dec(row[_COL_FERIE_MAT]),
                            ferie_goduti=_ced_dec(row[_COL_FERIE_GOD]),
                            ferie_residui=_ced_dec(row[_COL_FERIE_RES]),
                            permessi_anni_prec=_ced_dec(row[_COL_PERM_AP]),
                            permessi_maturati=_ced_dec(row[_COL_PERM_MAT]),
                            permessi_goduti=_ced_dec(row[_COL_PERM_GOD]),
                            permessi_residui=_ced_dec(row[_COL_PERM_RES]),
                            rol_anni_prec=_ced_dec(row[_COL_ROL_AP]),
                            rol_maturati=_ced_dec(row[_COL_ROL_MAT]),
                            rol_goduti=_ced_dec(row[_COL_ROL_GOD]),
                            rol_residui=_ced_dec(row[_COL_ROL_RES]),
                            ex_fest_anni_prec=_ced_dec(row[_COL_EXFEST_AP]),
                            ex_fest_maturati=_ced_dec(row[_COL_EXFEST_MAT]),
                            ex_fest_goduti=_ced_dec(row[_COL_EXFEST_GOD]),
                            ex_fest_residui=_ced_dec(row[_COL_EXFEST_RES]),
                        ),
                    )
                    ok += 1
                except Exception:
                    err += 1
                    scarti.append({"riga": n_riga, "chiave": cf, "motivo": "Errore di salvataggio (dettaglio nel log applicativo)"})
                    logger.exception("Errore import cedolino CF=%s mese=%s", cf, dt)

            imp.righe_ok = ok
            imp.righe_errore = err
            imp.righe_non_trovate = nf
            imp.scarti = scarti[:2000]
            imp.save(update_fields=["righe_ok", "righe_errore", "righe_non_trovate", "scarti"])
            totale_ok += ok
            totale_err += err
            totale_nf += nf
            ultima_imp = imp

    return ultima_imp


@login_required
def cedolini_import(request):
    """Pagina importazione XLSX cedolini (solo admin)."""
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    if not is_admin:
        messages.error(request, "Accesso riservato agli amministratori.")
        return redirect("anagrafica:dipendenti_list")

    from ..services import cedolini_sharepoint

    azione = request.POST.get("azione", "") if request.method == "POST" else ""
    if azione == "sharepoint_link":
        url = (request.POST.get("sharepoint_url") or "").strip()
        if url and not url.lower().startswith("https://"):
            messages.error(request, "Il link SharePoint deve iniziare con https://.")
        else:
            cedolini_sharepoint.set_share_url(url)
            messages.success(request, "Link SharePoint salvato." if url else "Link SharePoint rimosso.")
        return _ritorno_import(request, "anagrafica:ratei_list", "anagrafica:cedolini_import")
    if azione == "sharepoint_import":
        try:
            imp = cedolini_sharepoint.importa_da_sharepoint(user=request.user)
            messages.success(
                request,
                f"Importazione da SharePoint completata ({imp.data_competenza:%m/%Y}): {imp.righe_ok} saldi salvati"
                f"{f', {imp.righe_errore} errori' if imp.righe_errore else ''}"
                f"{f', {imp.righe_non_trovate} CF non in anagrafica' if imp.righe_non_trovate else ''}.",
            )
        except Exception as exc:
            logger.exception("Errore importazione cedolini da SharePoint")
            messages.error(request, f"Errore durante l'importazione da SharePoint: {exc}")
        return _ritorno_import(request, "anagrafica:ratei_list", "anagrafica:cedolini_import")

    if request.method == "POST":
        file_obj = request.FILES.get("file_xlsx")
        if not file_obj:
            messages.error(request, "Nessun file selezionato.")
        else:
            try:
                imp = _import_xlsx_cedolini(file_obj, request.user, file_obj.name)
                periodi_n = ImportazioneCedolini.objects.filter(file_nome=file_obj.name).count()
                messages.success(
                    request,
                    f"Importazione completata: {imp.righe_ok} saldi salvati"
                    f"{f', {imp.righe_errore} errori' if imp.righe_errore else ''}"
                    f"{f', {imp.righe_non_trovate} CF non in anagrafica' if imp.righe_non_trovate else ''}.",
                )
            except Exception as exc:
                logger.exception("Errore importazione XLSX cedolini")
                messages.error(request, f"Errore durante l'importazione: {exc}")
        return _ritorno_import(request, "anagrafica:ratei_list", "anagrafica:cedolini_import")
    if _helpers._check_hr_permission(request):
        return redirect(f"{reverse('anagrafica:ratei_list')}#importazione")

    importazioni = list(
        ImportazioneCedolini.objects
        .select_related("importato_da")
        .order_by("-data_competenza", "-data_importazione")[:50]
    )
    return render(request, "anagrafica/pages/cedolini_import.html", {
        "importazioni": importazioni,
        "is_admin": is_admin,
        "sharepoint_url": cedolini_sharepoint.get_share_url(),
    })


# Ratei ferie/ROL/ex-festività — vista aggregata con filtro mese + dipendente
# ---------------------------------------------------------------------------

@login_required
def ratei_list(request):
    """Lista aggregata saldi cedolini con filtro per periodo e dipendente (solo HR)."""
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    can_hr = _helpers._check_hr_permission(request)

    if not can_hr:
        messages.error(request, "Accesso non autorizzato ai dati HR.")
        return redirect("anagrafica:index")

    # Periodi disponibili
    periodi_qs = (
        SaldoCedolino.objects.values("data_competenza")
        .distinct()
        .order_by("-data_competenza")
    )
    periodi = [p["data_competenza"] for p in periodi_qs]

    # Build opzioni multi-select dipendente: tax_code → "Cognome Nome"
    all_cf_legacy = list(
        SaldoCedolino.objects.values("tax_code", "legacy_anagrafica_id")
        .distinct()
        .order_by("tax_code")
    )
    # Fallback CF → legacy_id via DipendenteAnagraficaCivile (per cedolini senza legacy_id)
    cf_civile_legacy: dict = {}
    for c in DipendenteAnagraficaCivile.objects.exclude(codice_fiscale="").values("codice_fiscale", "legacy_anagrafica_id"):
        cf_u = (c["codice_fiscale"] or "").strip().upper()
        if cf_u:
            cf_civile_legacy[cf_u] = c["legacy_anagrafica_id"]

    cf_to_legacy_rl: dict = {}
    for row in all_cf_legacy:
        cf = (row["tax_code"] or "").strip()
        if not cf or cf in cf_to_legacy_rl:
            continue
        cf_to_legacy_rl[cf] = row["legacy_anagrafica_id"] or cf_civile_legacy.get(cf.upper())

    legacy_ids = sorted({lid for lid in cf_to_legacy_rl.values() if lid})
    dip_qs = list(AnagraficaDipendente.objects.filter(id__in=legacy_ids).values("id", "cognome", "nome", "reparto"))
    id_to_nome: dict = {
        d["id"]: naming.nome_completo(d["nome"], d["cognome"])
        for d in dip_qs
    }
    # L'etichetta è "Nome Cognome", la tendina resta ordinata per cognome.
    id_to_ordine: dict = {
        d["id"]: naming.chiave_ordinamento(d["nome"], d["cognome"])
        for d in dip_qs
    }
    # Fallback reparto: AnagraficaDipendente.reparto → DipendenteAnagraficaAziendale.area
    id_to_az_reparto_rl: dict = dict(
        DipendenteAnagraficaAziendale.objects
        .filter(legacy_anagrafica_id__in=legacy_ids)
        .exclude(area="")
        .values_list("legacy_anagrafica_id", "area")
    )
    id_to_reparto: dict = {
        d["id"]: (d["reparto"] or id_to_az_reparto_rl.get(d["id"], "")).strip()
        for d in dip_qs
    }

    seen_cf: set = set()
    dipendenti_options: list = []
    for cf, lid in cf_to_legacy_rl.items():
        if cf in seen_cf:
            continue
        seen_cf.add(cf)
        nome = id_to_nome.get(lid) if lid else None
        reparto = id_to_reparto.get(lid, "") if lid else ""
        dipendenti_options.append({
            "cf": cf,
            "nome": nome or cf,
            "reparto": reparto,
            "_ordine": (id_to_ordine.get(lid) if lid else "") or nome or cf,
        })
    dipendenti_options.sort(key=lambda x: x["_ordine"].casefold())
    cf_to_nome: dict = {d["cf"]: d["nome"] for d in dipendenti_options}

    reparti_options: list = sorted({d["reparto"] for d in dipendenti_options if d["reparto"]})

    # Filtri GET — backward compat: ?cf=CF_CODE (link da dipendente_detail legacy)
    filtro_periodo = request.GET.get("periodo", "")
    filtro_dipendenti: list = request.GET.getlist("dipendente")
    if not filtro_dipendenti:
        cf_compat = request.GET.get("cf", "").strip().upper()
        if cf_compat:
            filtro_dipendenti = [cf_compat]
    filtro_reparti: list = request.GET.getlist("reparto")
    filtro_allerta: bool = request.GET.get("allerta", "") == "1"
    # 1.10 — filtro per valore del saldo con operatore di confronto (< > =)
    filtro_saldo_campo = request.GET.get("saldo_campo", "")
    filtro_saldo_op = request.GET.get("saldo_op", "")
    filtro_saldo_val = request.GET.get("saldo_val", "").strip()

    qs = SaldoCedolino.objects.all().order_by("-data_competenza", "tax_code")

    if filtro_periodo:
        try:
            from datetime import date as _date
            anno, mese, giorno = filtro_periodo.split("-")
            qs = qs.filter(data_competenza=_date(int(anno), int(mese), int(giorno)))
        except (ValueError, AttributeError):
            pass

    if filtro_reparti:
        ids_in_reparto = [lid for lid, rep in id_to_reparto.items() if rep in filtro_reparti]
        qs = qs.filter(legacy_anagrafica_id__in=ids_in_reparto)

    if filtro_dipendenti:
        qs = qs.filter(tax_code__in=filtro_dipendenti)

    # AB1-D — semaforo/alert residuo ferie (solo HR/amministrazione)
    from ..ratei_alert import (
        SALDO_CAMPI,
        SALDO_OPERATORI,
        filtro_allerta_q,
        saldo_filter_q,
        soglie_ratei,
        valuta_residuo_ferie,
    )

    _saldo_q = saldo_filter_q(filtro_saldo_campo, filtro_saldo_op, filtro_saldo_val)
    if _saldo_q is not None:
        qs = qs.filter(_saldo_q)
    soglie = soglie_ratei()
    # KPI sul set filtrato (periodo/dipendente/reparto), prima del toggle allerta
    n_negativi = qs.filter(ferie_residui__lt=0).count()
    n_accumulo = qs.filter(ferie_residui__gte=soglie["ore_max"]).count()
    n_allerta = qs.filter(filtro_allerta_q(soglie)).count()
    if filtro_allerta:
        qs = qs.filter(filtro_allerta_q(soglie))

    totale = qs.count()
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    for s in page_obj.object_list:
        s.nome_display = cf_to_nome.get(s.tax_code.upper(), s.tax_code)
        s.semaforo = valuta_residuo_ferie(s.ferie_residui, soglie)

    # Sezione «Importazione» (ex pagina cedolini_import): solo per gli admin.
    importazioni_cedolini, sharepoint_url = [], ""
    if is_admin:
        from ..services import cedolini_sharepoint

        importazioni_cedolini = list(
            ImportazioneCedolini.objects.select_related("importato_da")
            .order_by("-data_competenza", "-data_importazione")[:50]
        )
        sharepoint_url = cedolini_sharepoint.get_share_url()
    return render(request, "anagrafica/pages/ratei_list.html", {
        "importazioni_cedolini": importazioni_cedolini,
        "sharepoint_url": sharepoint_url,
        "page_obj": page_obj,
        "periodi": periodi,
        "filtro_periodo": filtro_periodo,
        "filtro_dipendenti": filtro_dipendenti,
        "filtro_reparti": filtro_reparti,
        "filtro_allerta": filtro_allerta,
        "filtro_saldo_campo": filtro_saldo_campo,
        "filtro_saldo_op": filtro_saldo_op,
        "filtro_saldo_val": filtro_saldo_val,
        "saldo_campi_options": SALDO_CAMPI,
        "saldo_operatori_options": SALDO_OPERATORI,
        "dipendenti_options": dipendenti_options,
        "reparti_options": reparti_options,
        "can_hr": can_hr,
        "is_admin": is_admin,
        "totale": totale,
        "soglie": soglie,
        "n_negativi": n_negativi,
        "n_accumulo": n_accumulo,
        "n_allerta": n_allerta,
    })


# ---------------------------------------------------------------------------
# Ratei ferie — export XLSX (stessa logica filtri di ratei_list)
# ---------------------------------------------------------------------------

@login_required
def ratei_export(request):
    """Scarica XLSX dei saldi cedolini con i filtri correnti (solo HR)."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment
    from openpyxl.utils import get_column_letter

    from core.excel_export import append_row

    can_hr = _helpers._check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso non autorizzato ai dati HR.")
        return redirect("anagrafica:index")

    # Mappa legacy_id → nome/reparto
    all_cf_legacy = list(
        SaldoCedolino.objects.values("tax_code", "legacy_anagrafica_id")
        .distinct()
        .order_by("tax_code")
    )
    cf_civile_legacy_exp: dict = {}
    for c in DipendenteAnagraficaCivile.objects.exclude(codice_fiscale="").values("codice_fiscale", "legacy_anagrafica_id"):
        cf_u = (c["codice_fiscale"] or "").strip().upper()
        if cf_u:
            cf_civile_legacy_exp[cf_u] = c["legacy_anagrafica_id"]

    cf_to_legacy_exp: dict = {}
    for row in all_cf_legacy:
        cf = (row["tax_code"] or "").strip()
        if not cf or cf in cf_to_legacy_exp:
            continue
        cf_to_legacy_exp[cf] = row["legacy_anagrafica_id"] or cf_civile_legacy_exp.get(cf.upper())

    legacy_ids = sorted({lid for lid in cf_to_legacy_exp.values() if lid})
    dip_qs = list(AnagraficaDipendente.objects.filter(id__in=legacy_ids).values("id", "cognome", "nome", "reparto"))
    id_to_nome: dict = {
        d["id"]: naming.nome_completo(d["nome"], d["cognome"])
        for d in dip_qs
    }
    id_to_az_reparto_exp: dict = dict(
        DipendenteAnagraficaAziendale.objects
        .filter(legacy_anagrafica_id__in=legacy_ids)
        .exclude(area="")
        .values_list("legacy_anagrafica_id", "area")
    )
    id_to_reparto: dict = {
        d["id"]: (d["reparto"] or id_to_az_reparto_exp.get(d["id"], "")).strip()
        for d in dip_qs
    }
    cf_to_nome: dict = {}
    cf_to_reparto: dict = {}
    for cf, lid in cf_to_legacy_exp.items():
        cf_to_nome[cf] = id_to_nome.get(lid, cf) if lid else cf
        cf_to_reparto[cf] = id_to_reparto.get(lid, "") if lid else ""

    # Filtri GET (identici a ratei_list)
    filtro_periodo = request.GET.get("periodo", "")
    filtro_dipendenti: list = request.GET.getlist("dipendente")
    if not filtro_dipendenti:
        cf_compat = request.GET.get("cf", "").strip().upper()
        if cf_compat:
            filtro_dipendenti = [cf_compat]
    filtro_reparti: list = request.GET.getlist("reparto")
    filtro_allerta: bool = request.GET.get("allerta", "") == "1"

    qs = SaldoCedolino.objects.all().order_by("-data_competenza", "tax_code")
    if filtro_periodo:
        try:
            anno, mese, giorno = filtro_periodo.split("-")
            qs = qs.filter(data_competenza=date(int(anno), int(mese), int(giorno)))
        except (ValueError, AttributeError):
            pass
    if filtro_reparti:
        ids_in_reparto = [lid for lid, rep in id_to_reparto.items() if rep in filtro_reparti]
        qs = qs.filter(legacy_anagrafica_id__in=ids_in_reparto)
    if filtro_dipendenti:
        qs = qs.filter(tax_code__in=filtro_dipendenti)
    # 1.10 — stesso filtro per valore/operatore della lista, per coerenza export
    from ..ratei_alert import saldo_filter_q as _saldo_filter_q
    _saldo_q = _saldo_filter_q(
        request.GET.get("saldo_campo", ""),
        request.GET.get("saldo_op", ""),
        request.GET.get("saldo_val", "").strip(),
    )
    if _saldo_q is not None:
        qs = qs.filter(_saldo_q)
    if filtro_allerta:
        from ..ratei_alert import filtro_allerta_q, soglie_ratei
        qs = qs.filter(filtro_allerta_q(soglie_ratei()))

    # --- Workbook ---
    wb = Workbook()
    ws = wb.active
    ws.title = "Ratei Ferie"

    fill_hdr  = PatternFill("solid", fgColor="F1F5F9")
    fill_fer  = PatternFill("solid", fgColor="FEF9C3")
    fill_rol  = PatternFill("solid", fgColor="DBEAFE")
    fill_exf  = PatternFill("solid", fgColor="DCFCE7")
    font_b    = Font(bold=True)
    font_fer  = Font(bold=True, color="854D0E")
    font_rol  = Font(bold=True, color="1E40AF")
    font_exf  = Font(bold=True, color="166534")
    c_center  = Alignment(horizontal="center", vertical="center", wrap_text=True)
    c_right   = Alignment(horizontal="right")

    # Riga 1 — gruppi
    groups = [
        ("A1:A2", "Dipendente",   fill_hdr, font_b),
        ("B1:B2", "Reparto",      fill_hdr, font_b),
        ("C1:C2", "Periodo",      fill_hdr, font_b),
        ("D1:D2", "Anzianità",    fill_hdr, font_b),
        ("E1:H1", "Ferie",        fill_fer, font_fer),
        ("I1:L1", "ROL",          fill_rol, font_rol),
        ("M1:P1", "Ex-Festività", fill_exf, font_exf),
    ]
    for rng, label, fill, fnt in groups:
        ws.merge_cells(rng)
        c = ws[rng.split(":")[0]]
        c.value = label; c.fill = fill; c.font = fnt; c.alignment = c_center

    # Riga 2 — sotto-intestazioni
    sub = [
        ("E", "Anni Prec.", fill_fer, font_fer), ("F", "Maturate",  fill_fer, font_fer),
        ("G", "Godute",     fill_fer, font_fer), ("H", "Residue",   fill_fer, font_fer),
        ("I", "Anni Prec.", fill_rol, font_rol), ("J", "Maturati",  fill_rol, font_rol),
        ("K", "Goduti",     fill_rol, font_rol), ("L", "Residui",   fill_rol, font_rol),
        ("M", "Anni Prec.", fill_exf, font_exf), ("N", "Maturate",  fill_exf, font_exf),
        ("O", "Godute",     fill_exf, font_exf), ("P", "Residue",   fill_exf, font_exf),
    ]
    for col, label, fill, fnt in sub:
        c = ws[f"{col}2"]
        c.value = label; c.fill = fill; c.font = fnt; c.alignment = c_center

    ws.freeze_panes = "A3"

    # Dati
    for s in qs.iterator():
        cf_upper = s.tax_code.upper()
        nome = cf_to_nome.get(cf_upper, s.tax_code)
        reparto = cf_to_reparto.get(cf_upper, "")
        periodo = s.data_competenza.strftime("%b %Y") if s.data_competenza else ""
        if s.anzianita_anni is not None:
            anz = f"{s.anzianita_anni}a"
            if s.anzianita_mesi:
                anz += f" {s.anzianita_mesi}m"
        else:
            anz = ""
        append_row(ws, [
            nome, reparto, periodo, anz,
            s.ferie_anni_prec, s.ferie_maturati, s.ferie_goduti, s.ferie_residui,
            s.rol_anni_prec, s.rol_maturati, s.rol_goduti, s.rol_residui,
            s.ex_fest_anni_prec, s.ex_fest_maturati, s.ex_fest_goduti, s.ex_fest_residui,
        ])

    # Larghezze colonne
    for i, w in enumerate([28, 20, 12, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Nome file
    parts = []
    if filtro_reparti:
        parts.append("_".join(r.replace(" ", "-") for r in filtro_reparti[:2]))
    if filtro_periodo:
        parts.append(filtro_periodo[:7])
    fname = "ratei_ferie" + (f"_{'_'.join(parts)}" if parts else "") + ".xlsx"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    return response


# ---------------------------------------------------------------------------
# Retribuzioni — vista globale pivot (dipendente+mese × pay_item) con filtri
# ---------------------------------------------------------------------------

_GENERE_LABEL = dict(DipendenteAnagraficaCivile.GENERE_CHOICES)


def _retribuzioni_globale_context(request) -> dict:
    """Costruisce dataset e filtri condivisi dalla vista globale retribuzioni e
    dal relativo export. Restituisce mappe display, colonne pivot, righe-gruppo
    (chiavi tax_code+mese ordinate) e i valori dei filtri correnti."""
    from django.db.models import Min

    # Coppie tax_code/legacy presenti nelle voci retributive
    all_pairs = list(
        VoceRetributiva.objects.values("tax_code", "legacy_anagrafica_id").distinct()
    )

    # Anagrafica civile: la voce retributiva non sempre ha `legacy_anagrafica_id`
    # valorizzato, quindi il collegamento al dipendente legacy (nome, reparto)
    # passa dal codice fiscale tramite l'anagrafica civile.
    cf_civile_legacy: dict = {}
    cf_to_sesso: dict = {}
    for c in (
        DipendenteAnagraficaCivile.objects
        .exclude(codice_fiscale="")
        .values("codice_fiscale", "legacy_anagrafica_id", "genere")
    ):
        cf_u = (c["codice_fiscale"] or "").strip().upper()
        if not cf_u:
            continue
        cf_civile_legacy[cf_u] = c["legacy_anagrafica_id"]
        cf_to_sesso[cf_u] = c["genere"] or ""

    # Mappa tax_code -> legacy_id: prima il valore della voce, poi l'anagrafica civile
    cf_to_legacy: dict = {}
    for p in all_pairs:
        cf = (p["tax_code"] or "").strip()
        if not cf or cf in cf_to_legacy:
            continue
        cf_to_legacy[cf] = p["legacy_anagrafica_id"] or cf_civile_legacy.get(cf.upper())

    legacy_ids = sorted({lid for lid in cf_to_legacy.values() if lid})

    dip_qs = list(
        AnagraficaDipendente.objects.filter(id__in=legacy_ids)
        .values("id", "cognome", "nome", "reparto")
    )
    id_to_nome = {
        d["id"]: naming.nome_completo(d["nome"], d["cognome"])
        for d in dip_qs
    }
    # L'etichetta è "Nome Cognome", la tendina resta ordinata per cognome.
    id_to_ordine = {
        d["id"]: naming.chiave_ordinamento(d["nome"], d["cognome"])
        for d in dip_qs
    }
    # Fallback reparto: AnagraficaDipendente.reparto → DipendenteAnagraficaAziendale.area
    _id_to_az_reparto: dict = dict(
        DipendenteAnagraficaAziendale.objects
        .filter(legacy_anagrafica_id__in=legacy_ids)
        .exclude(area="")
        .values_list("legacy_anagrafica_id", "area")
    )
    id_to_reparto = {
        d["id"]: (d["reparto"] or _id_to_az_reparto.get(d["id"], "")).strip()
        for d in dip_qs
    }

    # Livello contrattuale corrente: contratto piu' recente per dipendente
    id_to_livello: dict = {}
    cf_to_livello: dict = {}
    for sc in (
        StoricoContratto.objects
        .order_by("-data_inizio", "-created_at")
        .values("legacy_anagrafica_id", "tax_code", "codice_livello")
    ):
        liv = (sc["codice_livello"] or "").strip()
        if not liv:
            continue
        lid = sc["legacy_anagrafica_id"]
        cf = (sc["tax_code"] or "").strip().upper()
        if lid and lid not in id_to_livello:
            id_to_livello[lid] = liv
        if cf and cf not in cf_to_livello:
            cf_to_livello[cf] = liv

    def _nome(cf):
        lid = cf_to_legacy.get(cf)
        return (id_to_nome.get(lid) if lid else None) or cf

    def _reparto(cf):
        lid = cf_to_legacy.get(cf)
        return id_to_reparto.get(lid, "") if lid else ""

    def _sesso(cf):
        return cf_to_sesso.get(cf.upper(), "")

    def _livello(cf):
        lid = cf_to_legacy.get(cf)
        return (id_to_livello.get(lid) if lid else None) or cf_to_livello.get(cf.upper(), "")

    # Opzioni filtri
    def _ordine_cf(cf):
        lid = cf_to_legacy.get(cf)
        return ((id_to_ordine.get(lid) if lid else "") or _nome(cf)).casefold()

    dipendenti_options = sorted(
        ({"cf": cf, "nome": _nome(cf), "reparto": _reparto(cf)} for cf in cf_to_legacy),
        key=lambda x: _ordine_cf(x["cf"]),
    )
    reparti_options = sorted({r for r in id_to_reparto.values() if r})
    livelli_db = list(
        LivelloContrattuale.objects.filter(is_active=True)
        .order_by("ordine", "codice")
        .values_list("codice", flat=True)
    )
    livelli_usati = {_livello(cf) for cf in cf_to_legacy if _livello(cf)}
    livelli_options = list(dict.fromkeys(list(livelli_db) + sorted(livelli_usati)))
    periodi = list(
        VoceRetributiva.objects.values_list("data_competenza", flat=True)
        .distinct().order_by("-data_competenza")
    )

    # Filtri GET
    filtro_dipendenti = [c for c in request.GET.getlist("dipendente") if c.strip()]
    filtro_reparti = request.GET.getlist("reparto")
    filtro_sesso = request.GET.get("sesso", "").strip()
    filtro_livelli = [v.strip() for v in request.GET.getlist("livello") if v.strip()]
    filtro_periodo = request.GET.get("periodo", "")

    # Insieme tax_code ammessi dopo i filtri dipendente/reparto/sesso/livello
    allowed = set(cf_to_legacy.keys())
    if filtro_dipendenti:
        allowed &= set(filtro_dipendenti)
    if filtro_reparti:
        allowed = {cf for cf in allowed if _reparto(cf) in filtro_reparti}
    if filtro_sesso:
        allowed = {cf for cf in allowed if _sesso(cf) == filtro_sesso}
    if filtro_livelli:
        allowed = {cf for cf in allowed if _livello(cf) in filtro_livelli}

    has_filters = bool(filtro_dipendenti or filtro_reparti or filtro_sesso or filtro_livelli)
    qs = VoceRetributiva.objects.all()
    if has_filters:
        qs = qs.filter(tax_code__in=allowed)
    if filtro_periodo:
        try:
            anno, mese, giorno = filtro_periodo.split("-")
            qs = qs.filter(data_competenza=date(int(anno), int(mese), int(giorno)))
        except (ValueError, AttributeError):
            pass

    # Colonne pivot: tutti i pay_item del set filtrato, ordine di prima apparizione
    col_rows = list(
        qs.values("pay_item_key", "pay_item", "categoria")
        .annotate(_first=Min("data_competenza"))
        .order_by("_first")
    )
    _CAT_ORDER = {"fisso": 0, "variabile": 1, "altro": 2, "totale": 3}
    _TOTALI_SORT = {"retribuzione di fatto": 0, "totale elementi variabili": 1, "rml": 2, "ral": 3}
    key_meta: dict = {}
    seq = 0
    for r in col_rows:
        k = r["pay_item_key"]
        if k not in key_meta:
            key_meta[k] = {
                "key": k, "label": r["pay_item"], "categoria": r["categoria"], "_seq": seq,
            }
            seq += 1

    def _col_sort(m):
        cat = _CAT_ORDER.get(m["categoria"], 99)
        sub = _TOTALI_SORT.get(m["key"], 50) if m["categoria"] == "totale" else m["_seq"]
        return (cat, sub)

    colonne = sorted(key_meta.values(), key=_col_sort)

    _CAT_LABEL = dict(VoceRetributiva.CATEGORIA_CHOICES)
    gruppi: list = []
    for c in colonne:
        if gruppi and gruppi[-1]["categoria"] == c["categoria"]:
            gruppi[-1]["n"] += 1
        else:
            gruppi.append({
                "categoria": c["categoria"],
                "label": _CAT_LABEL.get(c["categoria"], c["categoria"]),
                "n": 1,
            })

    # Righe-gruppo: una per ogni combinazione dipendente+mese
    group_rows = list(
        qs.values("tax_code", "data_competenza").distinct()
        .order_by("-data_competenza", "tax_code")
    )

    return {
        "qs": qs,
        "colonne": colonne,
        "gruppi": gruppi,
        "group_rows": group_rows,
        "periodi": periodi,
        "dipendenti_options": dipendenti_options,
        "reparti_options": reparti_options,
        "livelli_options": livelli_options,
        "sesso_options": DipendenteAnagraficaCivile.GENERE_CHOICES,
        "filtro_dipendenti": filtro_dipendenti,
        "filtro_reparti": filtro_reparti,
        "filtro_sesso": filtro_sesso,
        "filtro_livelli": filtro_livelli,
        "filtro_periodo": filtro_periodo,
        "_nome": _nome,
        "_reparto": _reparto,
        "_sesso": _sesso,
        "_livello": _livello,
    }


def _retribuzioni_globale_rows(ctx: dict, groups: list) -> list:
    """Per un sottoinsieme di righe-gruppo costruisce le righe pivot effettive.

    Applica la stessa regola di merge della scheda dipendente: per ogni mese vale
    l'importazione CSV piu' recente, le voci manuali fanno override sullo stesso
    pay_item_key."""
    colonne = ctx["colonne"]
    qs = ctx["qs"]
    tax_set = {g["tax_code"] for g in groups}
    date_set = {g["data_competenza"] for g in groups}
    key_set = {(g["tax_code"], g["data_competenza"]) for g in groups}

    bucket: dict = {}
    for v in (
        qs.filter(tax_code__in=tax_set, data_competenza__in=date_set)
        .select_related("importazione")
    ):
        kk = (v.tax_code, v.data_competenza)
        if kk in key_set:
            bucket.setdefault(kk, []).append(v)

    rows: list = []
    for g in groups:
        cf = g["tax_code"]
        kk = (cf, g["data_competenza"])
        gv = bucket.get(kk, [])
        manuali = [v for v in gv if v.manuale]
        csv_voci = [v for v in gv if not v.manuale]
        if csv_voci:
            latest = max((v.importazione for v in csv_voci), key=lambda i: i.data_importazione)
            csv_voci = [v for v in csv_voci if v.importazione_id == latest.id]
        manuale_keys = {v.pay_item_key for v in manuali}
        eff = {v.pay_item_key: v for v in csv_voci if v.pay_item_key not in manuale_keys}
        eff.update({v.pay_item_key: v for v in manuali})

        celle = []
        for col in colonne:
            v = eff.get(col["key"])
            celle.append({
                "importo": v.importo if v else None,
                "manuale": bool(v and v.manuale),
                "is_totale": col["categoria"] == "totale",
            })
        sesso = ctx["_sesso"](cf)
        rows.append({
            "tax_code": cf,
            "legacy_anagrafica_id": gv[0].legacy_anagrafica_id if gv else None,
            "nome": ctx["_nome"](cf),
            "reparto": ctx["_reparto"](cf),
            "livello": ctx["_livello"](cf),
            "sesso": _GENERE_LABEL.get(sesso, sesso),
            "data_competenza": g["data_competenza"],
            "celle": celle,
        })
    return rows


@login_required
def retribuzioni_globale(request):
    """Vista globale voci retributive: una riga per dipendente+mese, colonne =
    pay_item raggruppate per categoria. Filtri per dipendente (multi), reparto,
    sesso e livello contrattuale (solo HR)."""
    can_hr = _helpers._check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso non autorizzato ai dati HR.")
        return redirect("anagrafica:index")

    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)

    ctx = _retribuzioni_globale_context(request)

    paginator = Paginator(ctx["group_rows"], 40)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    rows = _retribuzioni_globale_rows(ctx, list(page_obj.object_list))

    # Solo cedolini: contratti, ferie/permessi e scadenze hanno le loro pagine
    # (Scadenzario, «Ferie e permessi», Impostazioni → Amministrazione e import).
    ultima_importazione = (
        ImportazioneRetributiva.objects.filter(origine=ImportazioneRetributiva.ORIGINE_CSV)
        .order_by("-data_importazione").first()
    )

    # Sezione «Importazione» (ex pagina retribuzioni_import): solo per gli admin.
    importazioni_retribuzioni = list(
        ImportazioneRetributiva.objects
        .filter(origine=ImportazioneRetributiva.ORIGINE_CSV)
        .select_related("importato_da")[:30]
    ) if is_admin else []
    return render(request, "anagrafica/pages/retribuzioni_globale.html", {
        "importazioni_retribuzioni": importazioni_retribuzioni,
        "ultima_importazione": ultima_importazione,
        "page_obj": page_obj,
        "rows": rows,
        "colonne": ctx["colonne"],
        "gruppi": ctx["gruppi"],
        "n_colonne": len(ctx["colonne"]),
        "periodi": ctx["periodi"],
        "dipendenti_options": ctx["dipendenti_options"],
        "reparti_options": ctx["reparti_options"],
        "livelli_options": ctx["livelli_options"],
        "sesso_options": ctx["sesso_options"],
        "filtro_dipendenti": ctx["filtro_dipendenti"],
        "filtro_reparti": ctx["filtro_reparti"],
        "filtro_sesso": ctx["filtro_sesso"],
        "filtro_livelli": ctx["filtro_livelli"],
        "filtro_periodo": ctx["filtro_periodo"],
        "totale": len(ctx["group_rows"]),
        "can_hr": can_hr,
        "is_admin": is_admin,
    })


@login_required
def retribuzioni_globale_export(request):
    """Esporta in XLSX la vista globale retribuzioni con i filtri correnti (solo HR)."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment
    from openpyxl.utils import get_column_letter

    from core.excel_export import append_row, write_cell

    can_hr = _helpers._check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso non autorizzato ai dati HR.")
        return redirect("anagrafica:index")

    ctx = _retribuzioni_globale_context(request)
    colonne = ctx["colonne"]
    rows = _retribuzioni_globale_rows(ctx, ctx["group_rows"])

    wb = Workbook()
    ws = wb.active
    ws.title = "Retribuzioni"

    _CAT_FILL = {
        "fisso": PatternFill("solid", fgColor="EFF6FF"),
        "variabile": PatternFill("solid", fgColor="FEF9C3"),
        "totale": PatternFill("solid", fgColor="DCFCE7"),
        "altro": PatternFill("solid", fgColor="F1F5F9"),
    }
    fill_hdr = PatternFill("solid", fgColor="F1F5F9")
    font_b = Font(bold=True)
    c_center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    fixed = ["Dipendente", "Periodo", "Reparto", "Livello", "Sesso"]
    n_fixed = len(fixed)

    # Riga 1 — gruppi categoria
    for i, label in enumerate(fixed, 1):
        ws.merge_cells(start_row=1, start_column=i, end_row=2, end_column=i)
        c = write_cell(ws, 1, i, label)
        c.fill = fill_hdr
        c.font = font_b
        c.alignment = c_center
    col = n_fixed + 1
    for g in ctx["gruppi"]:
        start, end = col, col + g["n"] - 1
        if end > start:
            ws.merge_cells(start_row=1, start_column=start, end_row=1, end_column=end)
        c = write_cell(ws, 1, start, g["label"])
        c.fill = _CAT_FILL.get(g["categoria"], fill_hdr)
        c.font = font_b
        c.alignment = c_center
        col = end + 1

    # Riga 2 — pay_item
    for j, meta in enumerate(colonne):
        c = write_cell(ws, 2, n_fixed + 1 + j, meta["label"])
        c.fill = _CAT_FILL.get(meta["categoria"], fill_hdr)
        c.font = font_b
        c.alignment = c_center
    ws.freeze_panes = "A3"

    for r in rows:
        periodo = r["data_competenza"].strftime("%m-%Y") if r["data_competenza"] else ""
        line = [r["nome"], periodo, r["reparto"], r["livello"], r["sesso"]]
        for cell in r["celle"]:
            line.append(float(cell["importo"]) if cell["importo"] is not None else None)
        append_row(ws, line)

    ws.column_dimensions["A"].width = 28
    for i in range(2, n_fixed + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14
    for j in range(len(colonne)):
        ws.column_dimensions[get_column_letter(n_fixed + 1 + j)].width = 15

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = "retribuzioni_globale"
    if ctx["filtro_periodo"]:
        fname += f"_{ctx['filtro_periodo'][:7]}"
    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{fname}.xlsx"'
    return response
