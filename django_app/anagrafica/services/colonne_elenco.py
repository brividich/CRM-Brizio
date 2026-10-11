"""Registro delle colonne dell'elenco dipendenti (prompt 03).

Le colonne configurabili vengono SOLO da questo registro: la UI sceglie chiavi, mai campi
arbitrari, e nessun valore arriva da ``getattr`` su stringhe dell'utente. Ogni colonna dichiara
il permesso richiesto e se è sensibile: chi non ha il permesso non riceve la colonna né a video
(niente ``display:none``: i dati non entrano nell'HTML) né nell'export, anche se una vista o la
querystring la chiedono.

I valori si caricano a gruppi (una o due query per gruppo, a blocchi di 1000 id per il limite
di 2100 parametri di SQL Server): il numero di query non cresce con le righe.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.utils import timezone

# Permessi: chiave -> funzione di views.py che lo verifica (import pigro, views è grande).
PERMESSI = {
    "hr": ("_check_hr_permission", "Dati HR riservati"),
    "visite": ("_can_view_visite_mediche", "Visite mediche"),
    "formazione": ("_can_view_formazione", "Formazione"),
    "admin": ("_is_anagrafica_admin", "Amministrazione anagrafica"),
}


@dataclass(frozen=True)
class Colonna:
    chiave: str
    etichetta: str
    gruppo: str              # loader che la valorizza
    campo: str = ""          # campo del gruppo (dichiarato qui, mai dall'utente)
    tipo: str = "text"       # text | date | bool | number
    permesso: str = ""       # "" = visibile a chi vede l'elenco
    sensibile: bool = False
    ordinabile: bool = True
    filtrabile: bool = True
    esportabile: bool = True
    sezione: str = "Anagrafica"

    @property
    def permesso_label(self) -> str:
        return PERMESSI[self.permesso][1] if self.permesso else ""


REGISTRO: dict[str, Colonna] = {c.chiave: c for c in [
    # --- base (riga legacy) ---
    Colonna("reparto", "Reparto", "base", "reparto"),
    Colonna("area_aziendale", "Area aziendale", "base", "area_aziendale_nome"),
    Colonna("mansione", "Mansione", "base", "mansione"),
    Colonna("ruoli", "Ruoli ricoperti", "ruoli"),
    Colonna("email", "Email notifica", "base", "email_notifica"),
    Colonna("username", "Username", "base", "aliasusername"),
    Colonna("matricola", "Matricola", "base", "matricola"),
    Colonna("stato", "Scheda attiva", "base", "attivo", tipo="bool"),
    Colonna("account", "Account portale", "account", tipo="bool", sezione="Accesso"),
    # --- aziendale ---
    Colonna("badge", "Badge", "aziendale", "badge", sezione="Rapporto di lavoro"),
    Colonna("ruolo_aziendale", "Ruolo aziendale", "aziendale", "ruolo_aziendale", sezione="Rapporto di lavoro"),
    Colonna("tipologia_contratto", "Tipo contratto", "aziendale", "tipologia_contratto", sezione="Rapporto di lavoro"),
    Colonna("livello", "Livello inquadramento", "aziendale", "livello_inquadramento", permesso="hr", sensibile=True, sezione="Rapporto di lavoro"),
    Colonna("assunzione", "Prima assunzione", "aziendale", "data_prima_assunzione", tipo="date", sezione="Rapporto di lavoro"),
    Colonna("assunzione_ultima", "Ultima assunzione", "aziendale", "data_assunzione_ultima", tipo="date", sezione="Rapporto di lavoro"),
    Colonna("fine_prova", "Fine periodo di prova", "aziendale", "prova_data_fine", tipo="date", sezione="Rapporto di lavoro"),
    Colonna("email_aziendale", "Email aziendale", "aziendale", "email_aziendale", sezione="Contatti"),
    Colonna("telefono_aziendale", "Telefono aziendale", "aziendale", "telefono_aziendale", sezione="Contatti"),
    Colonna("consenso_privacy", "Consenso privacy", "aziendale", "consenso_privacy", tipo="bool", permesso="hr", sezione="Rapporto di lavoro"),
    # --- civile: dati personali estesi, solo con permesso HR ---
    Colonna("codice_fiscale", "Codice fiscale", "civile", "codice_fiscale", permesso="hr", sensibile=True, sezione="Dati personali"),
    Colonna("data_nascita", "Data di nascita", "civile", "data_nascita", tipo="date", permesso="hr", sensibile=True, sezione="Dati personali"),
    Colonna("luogo_nascita", "Luogo di nascita", "civile", "luogo_nascita", permesso="hr", sensibile=True, sezione="Dati personali"),
    Colonna("titolo_studio", "Titolo di studio", "civile", "titolo_studio", permesso="hr", sezione="Dati personali"),
    Colonna("email_privata", "Email privata", "civile", "email_privata", permesso="hr", sensibile=True, sezione="Dati personali"),
    Colonna("telefono_privato", "Telefono privato", "civile", "telefono_privato", permesso="hr", sensibile=True, sezione="Dati personali"),
    Colonna("categoria_protetta", "Categoria protetta", "civile", "categoria_protetta", tipo="bool", permesso="hr", sensibile=True, sezione="Dati personali"),
    # --- formazione e sicurezza ---
    Colonna("formazione_scaduta", "Corsi scaduti", "formazione", "scaduti", tipo="number", permesso="formazione", sezione="Formazione"),
    Colonna("formazione_in_scadenza", "Corsi in scadenza (90 gg)", "formazione", "in_scadenza", tipo="number", permesso="formazione", sezione="Formazione"),
    Colonna("visita_scadenza", "Prossima scadenza visita", "visite", "scadenza", tipo="date", permesso="visite", sensibile=True, sezione="Salute e sicurezza"),
    Colonna("visita_scaduta", "Visita scaduta", "visite", "scaduta", tipo="bool", permesso="visite", sensibile=True, sezione="Salute e sicurezza"),
    Colonna("timbri", "Timbri attivi", "timbri", tipo="number", sezione="Qualità"),
]}

DEFAULT_COLONNE = ["reparto", "mansione", "email"]


def _helper(nome):
    from .. import views

    return getattr(views, nome)


def permessi_utente(request) -> set[str]:
    """Permessi del registro che l'utente possiede (valutati una volta per richiesta)."""
    cache = getattr(request, "_colonne_permessi", None)
    if cache is not None:
        return cache
    out = set()
    for chiave, (funzione, _label) in PERMESSI.items():
        try:
            if _helper(funzione)(request):
                out.add(chiave)
        except Exception:  # noqa: BLE001 - fail-closed: in dubbio la colonna non c'è
            import logging

            logging.getLogger(__name__).exception("Permesso colonna %s non valutabile", chiave)
    request._colonne_permessi = out
    return out


def colonna_permessa(colonna: Colonna, permessi: set[str]) -> bool:
    return not colonna.permesso or colonna.permesso in permessi


def colonne_disponibili(request) -> list[Colonna]:
    permessi = permessi_utente(request)
    return [c for c in REGISTRO.values() if colonna_permessa(c, permessi)]


def colonne_da_specifica(specifica, request) -> list[dict]:
    """Specifica di una vista (``[{chiave, visibile, larghezza}]``) -> colonne utilizzabili.

    Le chiavi sconosciute si scartano e quelle non permesse spariscono: la vista può
    contenere una colonna sensibile senza che chi non ha il permesso la riceva."""
    permessi = permessi_utente(request)
    out = []
    for voce in specifica or []:
        if isinstance(voce, str):
            voce = {"chiave": voce}
        colonna = REGISTRO.get(str(voce.get("chiave") or ""))
        if colonna is None or not voce.get("visibile", True) or not colonna_permessa(colonna, permessi):
            continue
        try:
            larghezza = max(0, min(int(voce.get("larghezza") or 0), 600))
        except (TypeError, ValueError):
            larghezza = 0
        out.append({"colonna": colonna, "larghezza": larghezza})
    return out


# ---------------------------------------------------------------------------
# Caricamento valori a gruppi
# ---------------------------------------------------------------------------

def _blocchi(ids):
    lista = sorted(set(ids))
    for i in range(0, len(lista), 1000):
        yield lista[i:i + 1000]


def _carica_aziendale(ids, campi):
    from ..models import DipendenteAnagraficaAziendale

    out = {}
    for blocco in _blocchi(ids):
        for r in DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=blocco).values("legacy_anagrafica_id", *campi):
            out[r["legacy_anagrafica_id"]] = r
    return out


def _carica_civile(ids, campi):
    from ..models import DipendenteAnagraficaCivile

    out = {}
    for blocco in _blocchi(ids):
        for r in DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id__in=blocco).values("legacy_anagrafica_id", *campi):
            out[r["legacy_anagrafica_id"]] = r
    return out


def _carica_formazione(ids, _campi):
    from django.db.models import Count, Q

    from ..models_formazione import TrainingDeadline

    out = {}
    for blocco in _blocchi(ids):
        for r in (TrainingDeadline.objects.filter(legacy_anagrafica_id__in=blocco).order_by()
                  .values("legacy_anagrafica_id")
                  .annotate(scaduti=Count("pk", filter=Q(stato_scadenza="SCADUTO")),
                            in_scadenza=Count("pk", filter=Q(stato_scadenza__in=["IN_SCADENZA_30", "IN_SCADENZA_90"])))):
            out[r["legacy_anagrafica_id"]] = r
    return out


def _carica_visite(ids, _campi):
    from ..models import VisitaMedica

    oggi = timezone.localdate()
    out: dict[int, dict] = {}
    for blocco in _blocchi(ids):
        for lid, scadenza in (VisitaMedica.objects.filter(legacy_anagrafica_id__in=blocco, data_scadenza__isnull=False)
                              .order_by("legacy_anagrafica_id", "-data_scadenza").values_list("legacy_anagrafica_id", "data_scadenza")):
            # Vale l'ultima scadenza registrata per persona (la prima nell'ordine discendente).
            out.setdefault(lid, {"scadenza": scadenza, "scaduta": scadenza < oggi})
    return out


def _carica_account(rows):
    from core.legacy_models import UtenteLegacy

    ids = [int(r.get("utente_id") or 0) for r in rows if int(r.get("utente_id") or 0) > 0]
    attivi = {}
    for blocco in _blocchi(ids):
        attivi.update(dict(UtenteLegacy.objects.filter(id__in=blocco).values_list("id", "attivo")))
    return attivi


def _carica_timbri(ids):
    from django.db.models import Count, Q

    try:
        from timbri.models import RegistroTimbro
    except Exception:  # noqa: BLE001 - app timbri assente: colonna vuota
        return {}
    out = {}
    for blocco in _blocchi(ids):
        for lid, n in (RegistroTimbro.objects.filter(operatore__legacy_anagrafica_id__in=blocco).order_by()
                       .values("operatore__legacy_anagrafica_id")
                       .annotate(n=Count("pk", filter=Q(is_attivo=True, is_archived=False)))
                       .values_list("operatore__legacy_anagrafica_id", "n")):
            out[lid] = n
    return out


def _fmt(valore, tipo):
    if valore is None or valore == "":
        return ""
    if tipo == "bool":
        return "Sì" if valore else "No"
    if tipo == "date" and isinstance(valore, date):
        return valore.strftime("%d/%m/%Y")
    return str(valore)


def arricchisci(rows: list[dict], colonne: list[Colonna]) -> None:
    """Aggiunge a ogni riga ``valori[chiave] = (testo, valore_ordinamento)`` per le colonne date."""
    ids = [int(r.get("id") or 0) for r in rows if int(r.get("id") or 0) > 0]
    gruppi: dict[str, list[Colonna]] = {}
    for c in colonne:
        gruppi.setdefault(c.gruppo, []).append(c)
    dati: dict[str, dict] = {}
    if "aziendale" in gruppi:
        dati["aziendale"] = _carica_aziendale(ids, sorted({c.campo for c in gruppi["aziendale"]}))
    if "civile" in gruppi:
        dati["civile"] = _carica_civile(ids, sorted({c.campo for c in gruppi["civile"]}))
    if "formazione" in gruppi:
        dati["formazione"] = _carica_formazione(ids, None)
    if "visite" in gruppi:
        dati["visite"] = _carica_visite(ids, None)
    account = _carica_account(rows) if "account" in gruppi else {}
    timbri = _carica_timbri(ids) if "timbri" in gruppi else {}
    if "ruoli" in gruppi and not all("ruoli" in r for r in rows):
        from ..views import ruoli_ricoperti_map

        mappa = ruoli_ricoperti_map(ids)
        for r in rows:
            r["ruoli"] = mappa.get(int(r.get("id") or 0), [])
    for r in rows:
        lid = int(r.get("id") or 0)
        valori = {}
        for c in colonne:
            if c.gruppo == "base":
                grezzo = r.get(c.campo)
                if c.chiave == "stato":
                    grezzo = True if grezzo is None else bool(grezzo)
            elif c.gruppo == "account":
                grezzo = bool(account.get(int(r.get("utente_id") or 0)))
            elif c.gruppo == "timbri":
                grezzo = timbri.get(lid, 0)
            elif c.gruppo == "ruoli":
                grezzo = ", ".join(v["nome"] for v in r.get("ruoli") or [])
            else:
                grezzo = (dati.get(c.gruppo, {}).get(lid) or {}).get(c.campo)
            testo = _fmt(grezzo, c.tipo)
            ordine = grezzo.isoformat() if isinstance(grezzo, date) else testo
            valori[c.chiave] = (testo, ordine)
        r["valori"] = valori
