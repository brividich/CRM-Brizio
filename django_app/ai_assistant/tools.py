from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone

from core.legacy_utils import get_legacy_user


@dataclass(frozen=True)
class RuntimeContext:
    text: str = ""
    sources: tuple[str, ...] = ()
    audit: dict[str, Any] | None = None


RuntimeTool = Callable[[Any, str], RuntimeContext]
RUNTIME_CONTEXT_MAX_CHARS = 30000
RUNTIME_CONTEXT_MAX_LINES = 350


@dataclass(frozen=True)
class RuntimeToolSpec:
    key: str
    label: str
    domain: str
    audit_tool: str
    source_prefix: str
    status: str
    sample_prompt: str
    privacy_note: str


RUNTIME_TOOL_CATALOG: tuple[RuntimeToolSpec, ...] = (
    RuntimeToolSpec(
        key="runtime_router",
        label="Router cross-dominio",
        domain="Brief operativo",
        audit_tool="runtime_router",
        source_prefix="tool:runtime:router",
        status="enabled",
        sample_prompt="cosa devo fare oggi?",
        privacy_note="Combina solo i tool live gia autorizzati per l'utente simulato.",
    ),
    RuntimeToolSpec(
        key="module_catalog",
        label="Catalogo moduli",
        domain="Navigazione",
        audit_tool="module_catalog",
        source_prefix="tool:moduli",
        status="enabled",
        sample_prompt="quali moduli posso usare nel portale?",
        privacy_note="Espone soltanto voci di navigazione visibili, non contenuti dei moduli.",
    ),
    RuntimeToolSpec(
        key="assenze_periodo",
        label="Assenze",
        domain="Calendario",
        audit_tool="assenze_periodo",
        source_prefix="tool:assenze",
        status="enabled",
        sample_prompt="chi e' assente domani?",
        privacy_note="Rispetta i permessi calendario e limita il periodo richiesto.",
    ),
    RuntimeToolSpec(
        key="tickets_summary",
        label="Ticket",
        domain="Ticket",
        audit_tool="tickets_summary",
        source_prefix="tool:tickets",
        status="enabled",
        sample_prompt="quali ticket aperti ho?",
        privacy_note="Scope personale o gestionale calcolato dai permessi reali.",
    ),
    RuntimeToolSpec(
        key="tasks_summary",
        label="Task",
        domain="Attivita",
        audit_tool="tasks_summary",
        source_prefix="tool:tasks",
        status="enabled",
        sample_prompt="mostra i miei task in scadenza",
        privacy_note="Mostra solo task assegnati o visibili in base al ruolo.",
    ),
    RuntimeToolSpec(
        key="assets_summary",
        label="Asset",
        domain="Asset",
        audit_tool="assets_summary",
        source_prefix="tool:assets",
        status="enabled",
        sample_prompt="riepilogo asset e manutenzioni in scadenza",
        privacy_note="Filtra per asset personali o ambiti autorizzati.",
    ),
    RuntimeToolSpec(
        key="dpi_summary",
        label="DPI",
        domain="DPI",
        audit_tool="dpi_summary",
        source_prefix="tool:dpi",
        status="enabled",
        sample_prompt="mostra richieste dpi e scadenze",
        privacy_note="Limita l'output a richieste e scadenze pertinenti all'utente.",
    ),
    RuntimeToolSpec(
        key="anomalie_summary",
        label="Anomalie",
        domain="Anomalie",
        audit_tool="anomalie_summary",
        source_prefix="tool:anomalie",
        status="enabled",
        sample_prompt="riepilogo anomalie aperte",
        privacy_note="Usa solo dati operativi necessari e conteggi filtrati.",
    ),
    RuntimeToolSpec(
        key="procedure_refresh_summary",
        label="Procedure Refresh",
        domain="Procedure",
        audit_tool="procedure_refresh_summary",
        source_prefix="tool:procedure_refresh",
        status="enabled",
        sample_prompt="mostra le mie procedure e quiz",
        privacy_note="Utenti standard vedono solo assegnazioni personali; manager aggregati.",
    ),
    RuntimeToolSpec(
        key="notizie_summary",
        label="Notizie",
        domain="Comunicazioni",
        audit_tool="notizie_summary",
        source_prefix="tool:notizie",
        status="enabled",
        sample_prompt="mostra notizie obbligatorie da confermare",
        privacy_note="Non include corpo esteso o allegati.",
    ),
    RuntimeToolSpec(
        key="sicurezza_summary",
        label="Sicurezza",
        domain="Sicurezza",
        audit_tool="sicurezza_summary",
        source_prefix="tool:sicurezza",
        status="enabled",
        sample_prompt="mostra kpi sicurezza diario preposto e incidenti",
        privacy_note="Restituisce indicatori aggregati, non note sensibili.",
    ),
    RuntimeToolSpec(
        key="timbri_anagrafica",
        label="Timbri / Anagrafica",
        domain="HR",
        audit_tool="runtime_unavailable",
        source_prefix="tool:runtime:non-disponibile",
        status="deferred",
        sample_prompt="mostra timbrature e anagrafica dipendenti",
        privacy_note="Disabilitato: richiede revisione privacy dedicata prima del live.",
    ),
)


def get_runtime_tool_catalog() -> tuple[RuntimeToolSpec, ...]:
    return RUNTIME_TOOL_CATALOG


_ABSENCE_KEYWORDS = {
    "assente",
    "assenti",
    "assenza",
    "assenze",
    "ferie",
    "permesso",
    "permessi",
    "malattia",
    "malattie",
}
_MODULE_KEYWORDS = {
    "moduli",
    "modulo",
    "funzioni",
    "funzionalita",
    "funzionalità",
    "menu",
    "portale",
    "accessi",
    "posso fare",
    "dove trovo",
}
_TICKET_KEYWORDS = {
    "ticket",
    "tickets",
    "segnalazione",
    "segnalazioni",
    "richiesta assistenza",
    "richieste assistenza",
    "guasto",
    "guasti",
}
_TASK_KEYWORDS = {
    "task",
    "tasks",
    "attivit",
    "attivita",
    "attivita'",
    "kick-off",
    "kickoff",
    "progetto",
    "progetti",
    "gantt",
    "scadenza",
    "scadenze",
    "assegnazione",
    "assegnazioni",
    "assegnato",
    "assegnati",
    "ritardo",
    "ritardi",
    "scaduto",
    "scaduti",
}
_ASSET_KEYWORDS = {
    "asset",
    "assets",
    "bene",
    "beni",
    "macchina",
    "macchine",
    "macchinario",
    "macchinari",
    "dispositivo",
    "dispositivi",
    "pc",
    "notebook",
    "stampante",
    "server",
    "cnc",
    "carroponte",
    "carroponti",
    "manutenzione",
    "manutenzioni",
    "scadenza",
    "scadenze",
    "verifica",
    "verifiche",
    "work order",
    "workorder",
    "odl",
    "ordine di lavoro",
    "ordini di lavoro",
    "riparazione",
    "assegnati",
    "assegnato",
}
_DPI_KEYWORDS = {
    "dpi",
    "dispositivo di protezione",
    "dispositivi di protezione",
    "protezione individuale",
    "guanti",
    "guanto",
    "elmetto",
    "elmetti",
    "occhiali",
    "scarpe antinfortunistiche",
    "richiesta dpi",
    "richieste dpi",
    "consegna dpi",
    "consegne dpi",
}
_ANOMALIE_KEYWORDS = {
    "anomalia",
    "anomalie",
    "non conformita",
    "non conformita'",
    "non conformità",
    "rdc",
    "pezzo recuperato",
    "pezzi recuperati",
    "segnalazione produzione",
    "segnalazioni produzione",
}
_PROCEDURE_KEYWORDS = {
    "procedure refresh",
    "procedura",
    "procedure",
    "presa visione",
    "prese visione",
    "documenti da leggere",
    "documento da leggere",
    "quiz procedura",
    "quiz procedure",
    "formazione procedura",
    "formazione procedure",
    "campagna procedure",
    "campagne procedure",
}
_NOTIZIE_KEYWORDS = {
    "notizia",
    "notizie",
    "comunicazione",
    "comunicazioni",
    "avviso",
    "avvisi",
    "news",
    "obbligatorie",
    "obbligatoria",
}
_SICUREZZA_KEYWORDS = {
    "sicurezza",
    "diario preposto",
    "preposto",
    "segnalazioni sicurezza",
    "segnalazione sicurezza",
    "incidenti",
    "incidente",
    "infortunio",
    "infortuni",
    "near miss",
    "unsafe condition",
    "unsafe act",
    "rilevazione incidenti",
    "rilevazioni incidenti",
    "kpi sicurezza",
}
_UNAVAILABLE_DOMAIN_KEYWORDS = {
    "timbri",
    "timbrature",
    "cartellino",
    "cartellini",
    "presenze",
    "anagrafica",
    "anagrafiche",
    "dipendente",
    "dipendenti",
}
_RUNTIME_PRIORITY_BY_TOOL = {
    "runtime_router": 0,
    "sicurezza_summary": 10,
    "notizie_summary": 20,
    "procedure_refresh_summary": 30,
    "dpi_summary": 40,
    "assets_summary": 50,
    "tickets_summary": 60,
    "tasks_summary": 70,
    "anomalie_summary": 80,
    "assenze_periodo": 90,
    "module_catalog": 100,
    "runtime_unavailable": 110,
}


def _norm_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _wants_absence_list(prompt: str) -> bool:
    text = _norm_text(prompt)
    # Una domanda con un nome proprio + parola chiave assenza vale come richiesta
    has_name_hint = bool(re.search(r"\b(dipendente|dipendenti|persona|collega)\b", text))
    if not any(keyword in text for keyword in _ABSENCE_KEYWORDS) and not has_name_hint:
        return False
    return bool(
        re.search(r"\b(chi|quali|elenco|lista|riepilogo|mostra|dimmi|vedere|sono|scarica|dammi|fammi|quanti|giorni|fatti|effettuati?|registrati?)\b", text)
        or "assenti" in text
        or "assenze" in text
        or has_name_hint
    )


_NAME_STOPWORDS = {
    "assente", "assenti", "assenza", "assenze", "ferie", "permesso", "permessi",
    "malattia", "malattie", "dipendente", "dipendenti", "persona", "collega",
    "mese", "questo", "corrente", "gennaio", "febbraio", "marzo", "aprile",
    "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre",
    "dicembre", "oggi", "domani", "settimana", "anno", "reparto", "ufficio",
    "team", "sezione", "area", "effettuati", "registrati", "fatti", "fatto",
    "produzione", "magazzino", "amministrazione", "contabilita", "acquisti",
    # preposizioni e articoli che chiudono il nome
    "a", "al", "nel", "nella", "di", "da", "per", "in", "con", "su", "tra", "fra",
    "del", "della", "degli", "delle", "dei",
}


def _extract_name_filter(prompt: str) -> str:
    """Estrae un nome proprio dal prompt da usare come filtro dipendente (parziale, case-insensitive)."""
    for pattern in (
        r"(?:da|del dipendente|della dipendente|per il dipendente|per la dipendente)\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+){0,2})",
        r"(?:assenze|assenza|ferie|permessi?|malattia)\s+di\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+){0,2})",
        r"(?:ha fatto|effettuati?\s+da|registrati?\s+da|fatti\s+da)\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+){0,2})",
    ):
        m = re.search(pattern, prompt, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            # tronca appena incontra una stopword
            clean_words: list[str] = []
            for word in candidate.split():
                if word.lower() in _NAME_STOPWORDS:
                    break
                clean_words.append(word)
            candidate = " ".join(clean_words).strip()
            if candidate and len(candidate) >= 3:
                return candidate
    return ""


def _extract_reparto_filter(prompt: str) -> str:
    """Estrae il nome del reparto/team dal prompt."""
    text = _norm_text(prompt)
    m = re.search(
        r"(?:reparto|ufficio|team|sezione|area|settore|del reparto|del team|dell[ao] sezione|nell[ao] sezione|nel reparto)\s+([A-Za-zÀ-ÿ0-9 /\-]{2,40}?)(?:\s*\?|\s*\.|$|\s+(?:a|di|nel|per|del|in)\b)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return ""


def _extract_part_number_filter(prompt: str) -> str:
    """Estrae un part number dal prompt da usare come filtro anomalie/OP (parziale, case-insensitive)."""
    m = re.search(
        r"(?:part\s*number|codice\s*pezzo|pn|p/n|codice)\s*[:\s]+([A-Za-z0-9\-/\.]{3,30})",
        prompt,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    m = re.search(
        r"(?:sul|del|per il|per la|riguardanti il|riguardante il|relativ[io] al|con part number)\s+([A-Za-z0-9\-/\.]{3,30})",
        prompt,
        re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip()
        if len(candidate) >= 3:
            return candidate
    return ""


def _extract_incaricato_filter(prompt: str) -> str:
    """Estrae il nome di un incaricato/capocommessa dal prompt (anomalie, tasks)."""
    for pattern in (
        r"(?:incaricato|assegnate?\s+a|in\s+carico\s+a|capocomessa|capocommessa)\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+){0,2})",
        r"(?:di|per)\s+([A-Z][a-zÀ-ÿ]+(?:\s+[A-Z][a-zÀ-ÿ]+){0,2})\b",
    ):
        m = re.search(pattern, prompt, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            clean_words: list[str] = []
            for word in candidate.split():
                if word.lower() in _NAME_STOPWORDS:
                    break
                clean_words.append(word)
            candidate = " ".join(clean_words).strip()
            if candidate and len(candidate) >= 3:
                return candidate
    return ""


def _extract_assegnatario_filter(prompt: str) -> str:
    """Estrae il nome dell'assegnatario dal prompt (ticket, tasks, asset)."""
    for pattern in (
        r"(?:assegnat[aeio]\s+a|in\s+carico\s+a|gestit[aeio]\s+da|responsabile)\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+){0,2})",
        r"(?:ticket|task)\s+di\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+){0,2})",
    ):
        m = re.search(pattern, prompt, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            clean_words: list[str] = []
            for word in candidate.split():
                if word.lower() in _NAME_STOPWORDS:
                    break
                clean_words.append(word)
            candidate = " ".join(clean_words).strip()
            if candidate and len(candidate) >= 3:
                return candidate
    return ""


def _apply_row_filters(rows: list[dict], filters_map: dict[str, list[str]]) -> tuple[list[dict], list[str]]:
    """Applica filtri post-ACL su una lista di dizionari.

    filters_map: {valore_da_cercare: [campo1, campo2, ...]}
    Restituisce (righe_filtrate, etichette_filtri_applicati).
    """
    applied: list[str] = []
    for value, fields in filters_map.items():
        if not value:
            continue
        val_lower = value.lower()
        rows = [
            r for r in rows
            if any(val_lower in str(r.get(f) or "").lower() for f in fields)
        ]
        applied.append(f"'{value}' in {'/'.join(fields)}")
    return rows, applied


def _wants_module_catalog(prompt: str) -> bool:
    text = _norm_text(prompt)
    if not any(keyword in text for keyword in _MODULE_KEYWORDS):
        return False
    return bool(
        re.search(r"\b(che|quali|cosa|dove|elenco|lista|mostra|vedere|accedere|trovo|posso)\b", text)
        or "posso fare" in text
    )


def _wants_ticket_context(prompt: str) -> bool:
    text = _norm_text(prompt)
    if not any(keyword in text for keyword in _TICKET_KEYWORDS):
        return False
    return bool(
        re.search(
            r"\b(chi|quali|elenco|lista|riepilogo|mostra|dimmi|vedere|sono|ho|miei|mie|personali|aperti|aperte|urgenti)\b",
            text,
        )
        or re.search(r"\b(chiusi|chiuse|risolti|risolte|storico)\b", text)
    )


def _wants_task_context(prompt: str) -> bool:
    text = _norm_text(prompt)
    if not any(keyword.lower() in text for keyword in _TASK_KEYWORDS):
        return False
    explicit_task_domain = any(
        keyword in text
        for keyword in ("task", "tasks", "attivit", "kick-off", "kickoff", "progetto", "progetti", "gantt")
    )
    if any(keyword in text for keyword in _ASSET_KEYWORDS) and not explicit_task_domain:
        return False
    return bool(
        re.search(
            r"\b(chi|quali|elenco|lista|riepilogo|mostra|dimmi|vedere|sono|ho|miei|mie|personali|aperti|aperte|in corso|ritardo|scadenz[ae]|assegnat[ioe]|progetti?)\b",
            text,
        )
        or "kick-off" in text
        or "kickoff" in text
    )


def _wants_asset_context(prompt: str) -> bool:
    text = _norm_text(prompt)
    if not any(keyword in text for keyword in _ASSET_KEYWORDS):
        return False
    return bool(
        re.search(
            r"\b(chi|quali|elenco|lista|riepilogo|mostra|dimmi|vedere|sono|ho|miei|mie|assegnat[ioe]|scadenz[ae]|manutenzion[ei]|riparazion[ei]|apert[ioe]|stato|operativ[ao])\b",
            text,
        )
        or "work order" in text
        or "ordine di lavoro" in text
    )


def _wants_dpi_context(prompt: str) -> bool:
    text = _norm_text(prompt)
    if not any(keyword in text for keyword in _DPI_KEYWORDS):
        return False
    return bool(
        re.search(
            r"\b(chi|quali|elenco|lista|riepilogo|mostra|dimmi|vedere|sono|ho|miei|mie|personali|richiest[ae]|consegn[ae]|scadenz[ae]|scadut[ioe]|apert[ae]|approvat[ae]|rifiutat[ae]|conformit[ae])\b",
            text,
        )
        or "dpi" in text
    )


def _wants_anomalie_context(prompt: str) -> bool:
    text = _norm_text(prompt)
    if not any(keyword in text for keyword in _ANOMALIE_KEYWORDS):
        return False
    return bool(
        re.search(
            r"\b(chi|quali|elenco|lista|riepilogo|mostra|dimmi|vedere|sono|ho|mie|miei|aperte|aperti|chiuse|chiusi|stato|rdc|produzione)\b",
            text,
        )
        or "anomali" in text
    )


def _wants_procedure_context(prompt: str) -> bool:
    text = _norm_text(prompt)
    if not any(keyword in text for keyword in _PROCEDURE_KEYWORDS):
        return False
    return bool(
        re.search(
            r"\b(chi|quali|elenco|lista|riepilogo|mostra|dimmi|vedere|sono|ho|miei|mie|personali|assegnat[aeio]|scadenz[ae]|scadut[aeio]|lett[ioe]|leggere|confermat[aeio]|quiz|formazione|campagn[ae])\b",
            text,
        )
        or "presa visione" in text
        or "prese visione" in text
    )


def _wants_notizie_context(prompt: str) -> bool:
    text = _norm_text(prompt)
    if not any(keyword in text for keyword in _NOTIZIE_KEYWORDS):
        return False
    return bool(
        re.search(
            r"\b(chi|quali|elenco|lista|riepilogo|mostra|dimmi|vedere|sono|ho|mie|miei|pubblicat[aeio]|leggere|lette|non lette|confermare|obbligatorie|obbligatoria|compliance)\b",
            text,
        )
        or "notizi" in text
        or "comunicazion" in text
    )


def _wants_sicurezza_context(prompt: str) -> bool:
    text = _norm_text(prompt)
    if not any(keyword in text for keyword in _SICUREZZA_KEYWORDS):
        return False
    return bool(
        re.search(
            r"\b(chi|quali|elenco|lista|riepilogo|mostra|dimmi|vedere|sono|ho|kpi|trend|conteggi|statistiche|anno|mese|incidenti|infortuni|preposto|segnalazioni)\b",
            text,
        )
        or "near miss" in text
        or "diario preposto" in text
    )


def _wants_cross_domain_brief(prompt: str) -> bool:
    text = _norm_text(prompt)
    if re.search(
        r"\b(sui|sulle|sugli|sulla|sul|nei|nelle|negli|nella|nel|per i|per le|per gli|solo)\s+"
        r"(task|tasks|ticket|assets?|asset|dpi|procedure|notizie|sicurezza|anomalie|assenze)\b",
        text,
    ):
        return False
    return bool(
        "cosa devo fare" in text
        or "che devo fare" in text
        or "cose da fare" in text
        or "da fare oggi" in text
        or "priorita oggi" in text
        or "prioritÃ  oggi" in text
        or "priorita della giornata" in text
        or "riepilogo operativo" in text
        or "situazione operativa" in text
        or "scadenze di oggi" in text
    )


def _wants_unavailable_domain_context(prompt: str) -> bool:
    text = _norm_text(prompt)
    if not any(keyword in text for keyword in _UNAVAILABLE_DOMAIN_KEYWORDS):
        return False
    return bool(
        re.search(
            r"\b(chi|quali|elenco|lista|riepilogo|mostra|dimmi|vedere|sono|ho|leggere|cercare|consultare|presenze|timbrature|cartellin[io]|dipendenti?)\b",
            text,
        )
    )


_MONTH_NAMES: dict[str, int] = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def _target_period(prompt: str) -> tuple[str, datetime, datetime] | None:
    import calendar as _cal
    text = _norm_text(prompt)
    today = timezone.localdate()
    if "domani" in text:
        day = today + timedelta(days=1)
        label = f"domani ({day.strftime('%d/%m/%Y')})"
        start = datetime.combine(day, datetime.min.time())
        return label, start, start + timedelta(days=1)
    if "oggi" in text:
        day = today
        label = f"oggi ({day.strftime('%d/%m/%Y')})"
        start = datetime.combine(day, datetime.min.time())
        return label, start, start + timedelta(days=1)
    if "settimana" in text:
        start_day = today - timedelta(days=today.weekday())
        end_day = start_day + timedelta(days=7)
        label = f"questa settimana ({start_day.strftime('%d/%m/%Y')}-{(end_day - timedelta(days=1)).strftime('%d/%m/%Y')})"
        return label, datetime.combine(start_day, datetime.min.time()), datetime.combine(end_day, datetime.min.time())
    if "questo mese" in text or "mese corrente" in text:
        first = today.replace(day=1)
        last_day = _cal.monthrange(first.year, first.month)[1]
        last = first.replace(day=last_day)
        label = f"questo mese ({first.strftime('%B %Y')})"
        return label, datetime.combine(first, datetime.min.time()), datetime.combine(last + timedelta(days=1), datetime.min.time())
    # riconosce "gennaio 2026", "gennaio", "mese di gennaio 2026", ecc.
    for month_name, month_num in _MONTH_NAMES.items():
        if month_name in text:
            year_match = re.search(r"\b(20\d{2})\b", text)
            year = int(year_match.group(1)) if year_match else today.year
            first = date(year, month_num, 1)
            last_day = _cal.monthrange(year, month_num)[1]
            last = date(year, month_num, last_day)
            label = f"{month_name.capitalize()} {year}"
            return label, datetime.combine(first, datetime.min.time()), datetime.combine(last + timedelta(days=1), datetime.min.time())
    return None


def _target_date_window(prompt: str) -> tuple[str, date, date] | None:
    import calendar as _cal
    text = _norm_text(prompt)
    today = timezone.localdate()
    if "domani" in text:
        day = today + timedelta(days=1)
        return f"domani ({day.strftime('%d/%m/%Y')})", day, day
    if "oggi" in text:
        return f"oggi ({today.strftime('%d/%m/%Y')})", today, today
    if "settimana" in text:
        start_day = today - timedelta(days=today.weekday())
        end_day = start_day + timedelta(days=6)
        return f"questa settimana ({start_day.strftime('%d/%m/%Y')}-{end_day.strftime('%d/%m/%Y')})", start_day, end_day
    if "questo mese" in text or "mese corrente" in text:
        first = today.replace(day=1)
        last_day = _cal.monthrange(first.year, first.month)[1]
        return f"questo mese ({first.strftime('%B %Y')})", first, first.replace(day=last_day)
    for month_name, month_num in _MONTH_NAMES.items():
        if month_name in text:
            year_match = re.search(r"\b(20\d{2})\b", text)
            year = int(year_match.group(1)) if year_match else today.year
            first = date(year, month_num, 1)
            last_day = _cal.monthrange(year, month_num)[1]
            return f"{month_name.capitalize()} {year}", first, date(year, month_num, last_day)
    return None


def _short_datetime(value) -> str:
    if not value:
        return "N/D"
    try:
        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M")
    except (AttributeError, ValueError):
        return str(value)


def _short_date(value) -> str:
    if not value:
        return "N/D"
    try:
        return value.strftime("%d/%m/%Y")
    except AttributeError:
        return str(value)


def _display_user(user) -> str:
    if not user:
        return "non assegnato"
    full_name = ""
    try:
        full_name = user.get_full_name()
    except AttributeError:
        full_name = ""
    return (full_name or getattr(user, "username", "") or str(user)).strip() or "non assegnato"


def _row_line(row: dict[str, Any]) -> str:
    dipendente = str(row.get("dipendente") or "N/D").strip()
    tipo = str(row.get("tipo") or "Assenza").strip()
    stato = str(row.get("consenso") or "N/D").strip()
    inizio = str(row.get("inizio_label") or "").strip()
    fine = str(row.get("fine_label") or "").strip()
    dates = f" ({inizio} - {fine})" if inizio or fine else ""
    return f"- {dipendente}: {tipo}, stato {stato}{dates}"


def _ticket_line(ticket) -> str:
    assigned = (ticket.assegnato_a or "").strip() or "non assegnato"
    requester = (ticket.richiedente_nome or "").strip() or "N/D"
    return (
        f"- {ticket.numero_ticket}: {ticket.titolo}, {ticket.label_tipo}, stato {ticket.label_stato}, "
        f"priorita {ticket.label_priorita}, richiedente {requester}, assegnato a {assigned}, "
        f"aperto {_short_datetime(ticket.created_at)}"
    )


def _task_line(task, today: date) -> str:
    project = getattr(task, "project", None)
    project_name = getattr(project, "name", "") or "senza progetto"
    status = task.get_status_display() if hasattr(task, "get_status_display") else str(getattr(task, "status", "N/D"))
    assigned = _display_user(getattr(task, "assigned_to", None))
    due_date = getattr(task, "due_date", None)
    start_date = getattr(task, "next_step_due", None)
    overdue = bool(due_date and due_date < today and getattr(task, "status", "") not in {"DONE", "CANCELED"})
    late_label = ", in ritardo" if overdue else ""
    return (
        f"- {project_name}: {task.title}, stato {status}, assegnato a {assigned}, "
        f"inizio {_short_date(start_date)}, scadenza {_short_date(due_date)}{late_label}"
    )


def _project_line(project) -> str:
    number = getattr(project, "kickoff_number", None)
    prefix = f"KICK-OFF {number}" if number else str(getattr(project, "name", "") or "KICK-OFF")
    pm = _display_user(getattr(project, "project_manager", None))
    cc = _display_user(getattr(project, "capo_commessa", None))
    programmer = _display_user(getattr(project, "programmer", None))
    return f"- {prefix}: PM {pm}, capocommessa {cc}, programmatore {programmer}"


def _asset_line(asset) -> str:
    status = asset.get_status_display() if hasattr(asset, "get_status_display") else str(getattr(asset, "status", "N/D"))
    asset_type = asset.get_asset_type_display() if hasattr(asset, "get_asset_type_display") else str(getattr(asset, "asset_type", "N/D"))
    category = getattr(getattr(asset, "asset_category", None), "label", "") or asset_type
    assigned = str(getattr(asset, "assignment_to", "") or "").strip() or "non assegnato"
    reparto = str(getattr(asset, "assignment_reparto", "") or getattr(asset, "reparto", "") or "").strip() or "N/D"
    location = str(getattr(asset, "assignment_location", "") or "").strip()
    location_text = f", collocazione {location}" if location else ""
    return (
        f"- {asset.asset_tag}: {asset.name}, {category}, stato {status}, "
        f"responsabile {assigned}, reparto {reparto}{location_text}"
    )


def _deadline_line(deadline, today: date) -> str:
    asset = getattr(deadline, "asset", None)
    asset_label = f"{getattr(asset, 'asset_tag', 'N/D')} {getattr(asset, 'name', '')}".strip()
    kind = deadline.get_deadline_type_display() if hasattr(deadline, "get_deadline_type_display") else "Scadenza"
    days = deadline.days_until_due(today) if hasattr(deadline, "days_until_due") else None
    timing = "scaduta" if days is not None and days < 0 else f"tra {days} giorni" if days is not None else "N/D"
    return f"- {asset_label}: {deadline.title}, {kind}, scadenza {_short_date(deadline.due_date)} ({timing})"


def _workorder_line(workorder) -> str:
    asset = getattr(workorder, "asset", None)
    asset_label = f"{getattr(asset, 'asset_tag', 'N/D')} {getattr(asset, 'name', '')}".strip()
    status = workorder.get_status_display() if hasattr(workorder, "get_status_display") else str(getattr(workorder, "status", "N/D"))
    kind = workorder.get_kind_display() if hasattr(workorder, "get_kind_display") else str(getattr(workorder, "kind", "N/D"))
    return f"- {asset_label}: {workorder.title}, {kind}, stato {status}, aperto {_short_datetime(workorder.opened_at)}"


def _verification_line(verification) -> str:
    try:
        assets = list(verification.assets.all()[:3])
    except Exception:
        assets = []
    labels = ", ".join(f"{asset.asset_tag} {asset.name}".strip() for asset in assets) if assets else "asset non specificati"
    return f"- {verification.name}: prossima verifica {_short_date(verification.next_verification_date)}, asset {labels}"


def _dpi_item_label(richiesta) -> str:
    pieces = [getattr(richiesta.categoria, "nome", "") or "DPI"]
    if getattr(richiesta, "tipo_dpi", None):
        pieces.append(richiesta.tipo_dpi.nome)
    if getattr(richiesta, "modello_dpi", None):
        pieces.append(richiesta.modello_dpi.nome)
    if getattr(richiesta, "taglia_dpi", None):
        pieces.append(f"taglia {richiesta.taglia_dpi.valore}")
    return " / ".join(piece for piece in pieces if piece)


def _dpi_line(richiesta, *, include_requester: bool) -> str:
    consegna = getattr(richiesta, "consegna", None)
    requester = f", richiedente {richiesta.richiedente_nome}" if include_requester else ""
    delivery = ""
    if consegna:
        delivery = f", consegnato {_short_date(consegna.data_consegna)}"
        if consegna.data_scadenza_stimata:
            delivery += f", scadenza {_short_date(consegna.data_scadenza_stimata)}"
    return (
        f"- {richiesta.numero}: {_dpi_item_label(richiesta)}, quantita {richiesta.quantita}, "
        f"stato {richiesta.label_stato}{requester}{delivery}, aperta {_short_datetime(richiesta.created_at)}"
    )


def _bool_label(value) -> str:
    if value in (True, 1, "1", "true", "True", "SI", "Si", "si", "Sì", "sì"):
        return "si"
    if value in (False, 0, "0", "false", "False", "NO", "No", "no"):
        return "no"
    return "N/D" if value in (None, "") else str(value)


def _anomalie_line(row: dict[str, Any]) -> str:
    identifier = row.get("id") or row.get("local_id") or row.get("sharepoint_item_id") or "N/D"
    op = row.get("ex_op_nominativo") or row.get("title") or "OP non specificata"
    part_number = row.get("part_number") or ""
    op_suffix = f" ({part_number})" if part_number else ""
    seriale = row.get("seriale") or "N/D"
    status = "chiusa" if _bool_label(row.get("chiudere")) == "si" else "aperta"
    avanzamento = row.get("avanzamento") or "N/D"
    rdc = row.get("numero_rdc") or ("da aprire" if _bool_label(row.get("aprire_rdc")) == "si" else "no")
    recuperato = _bool_label(row.get("pezzo_recuperato"))
    cliente = _bool_label(row.get("segnalare_cliente"))
    modified = _short_datetime(row.get("modified_datetime"))
    return (
        f"- Anomalia {identifier}: OP {op}{op_suffix}, seriale {seriale}, stato {status}, "
        f"avanzamento {avanzamento}, pezzo recuperato {recuperato}, RDC {rdc}, "
        f"cliente da segnalare {cliente}, aggiornata {modified}"
    )


def _procedure_quiz_summary(quiz, attempt) -> str:
    if not quiz:
        return "quiz non previsto"
    if attempt:
        total = getattr(attempt, "total_questions", 0) or 0
        score = getattr(attempt, "score", 0) or 0
        percent = round((score / total) * 100) if total else 0
        return f"quiz {quiz.title}, esito {score}/{total} ({percent}%), inviato {_short_datetime(attempt.submitted_at)}"
    return f"quiz {quiz.title}, non inviato"


def _procedure_assignment_line(assignment, quiz_by_revision: dict[int, Any], attempt_by_assignment: dict[int, Any]) -> str:
    campaign = assignment.campaign
    revision = assignment.revision
    document = revision.document
    status = assignment.get_status_display() if hasattr(assignment, "get_status_display") else str(assignment.status)
    confirmed = _short_datetime(assignment.read_confirmed_at) if assignment.read_confirmed_flag else "non confermata"
    quiz = quiz_by_revision.get(revision.pk)
    attempt = attempt_by_assignment.get(assignment.pk)
    return (
        f"- {campaign.name}: {document.code} {document.title}, tipo {document.document_type}, "
        f"rev. {revision.revision_code}, stato {status}, scadenza {_short_date(assignment.due_date)}, "
        f"presa visione {confirmed}, {_procedure_quiz_summary(quiz, attempt)}"
    )


def _procedure_campaign_line(campaign) -> str:
    status = campaign.get_status_display() if hasattr(campaign, "get_status_display") else str(campaign.status)
    total = getattr(campaign, "assignment_count", 0) or 0
    confirmed = getattr(campaign, "confirmed_count", 0) or 0
    pending = getattr(campaign, "pending_count", 0) or 0
    overdue = getattr(campaign, "overdue_count", 0) or 0
    documents = getattr(campaign, "document_count", 0) or 0
    percent = round((confirmed / total) * 100) if total else 0
    return (
        f"- {campaign.name}: stato {status}, inizio {_short_date(campaign.start_date)}, "
        f"scadenza {_short_date(campaign.due_date)}, documenti {documents}, assegnazioni {total}, "
        f"confermate {confirmed} ({percent}%), pendenti {pending}, scadute {overdue}"
    )


def _notizia_line(notizia, compliance: str) -> str:
    mandatory = "obbligatoria" if getattr(notizia, "obbligatoria", False) else "informativa"
    attachment_count = getattr(notizia, "attachment_count", 0) or 0
    attachments = f", allegati {attachment_count}" if attachment_count else ", nessun allegato registrato"
    return (
        f"- {notizia.titolo}: {mandatory}, versione {notizia.versione}, "
        f"pubblicata {_short_datetime(notizia.pubblicato_il)}, compliance utente {compliance}{attachments}"
    )


def _safety_trend_line(item: dict[str, Any]) -> str:
    return f"{item.get('label')}: {item.get('count', 0)}"


def _legacy_identity(request) -> tuple[str, str, int | None]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user is not None:
        request.legacy_user = legacy_user
    name = str(getattr(legacy_user, "nome", "") or "").strip()
    email = str(getattr(legacy_user, "email", "") or "").strip()
    if not name:
        name = (request.user.get_full_name() or request.user.get_username() or "").strip()
    if not email:
        email = str(getattr(request.user, "email", "") or "").strip()
    legacy_id = getattr(legacy_user, "id", None)
    try:
        legacy_id = int(legacy_id) if legacy_id is not None else None
    except (TypeError, ValueError):
        legacy_id = None
    return name, email, legacy_id


def _row_line_extended(row: dict) -> str:
    """Versione estesa di _row_line che include il reparto se disponibile."""
    dipendente = str(row.get("dipendente") or "N/D")
    tipo = str(row.get("tipo") or row.get("tipo_assenza") or "N/D")
    stato = str(row.get("consenso") or "N/D")
    inizio = str(row.get("inizio_label") or "N/D")
    fine = str(row.get("fine_label") or "N/D")
    capo = str(row.get("capo") or "").strip()
    reparto_part = f", reparto: {capo}" if capo else ""
    return f"- {dipendente}{reparto_part}: {tipo}, dal {inizio} al {fine}, stato: {stato}"


def _aggregate_absences(rows: list[dict]) -> str:
    """Aggrega le righe assenze per dipendente per ridurre il testo inviato al modello.

    Produce una riga per dipendente con tutti i tipi di assenza e il numero di eventi,
    mantenendo tutte le informazioni senza troncamenti.
    """
    from collections import defaultdict
    by_person: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = str(row.get("dipendente") or "N/D").strip()
        by_person[key].append(row)

    out_lines: list[str] = []
    for dipendente in sorted(by_person):
        person_rows = by_person[dipendente]
        display_name = dipendente.title()
        capo = str(person_rows[0].get("capo") or "").strip()
        reparto_part = f" [{capo.title()}]" if capo else ""
        eventi: list[str] = []
        for r in person_rows:
            tipo = str(r.get("tipo") or "Assenza").strip()
            inizio = str(r.get("inizio_label") or "").strip()
            fine = str(r.get("fine_label") or "").strip()
            stato = str(r.get("consenso") or "").strip()
            # rimuove ore e anno (rumore): mostra solo gg/mm
            inizio_d = inizio.split(" ")[0] if " " in inizio else inizio
            fine_d = fine.split(" ")[0] if " " in fine else fine
            inizio_d = "/".join(inizio_d.split("/")[:2]) if inizio_d.count("/") == 2 else inizio_d
            fine_d = "/".join(fine_d.split("/")[:2]) if fine_d.count("/") == 2 else fine_d
            date_part = inizio_d + (f"-{fine_d}" if fine_d and fine_d != inizio_d else "")
            eventi.append(f"{tipo} {date_part}" + (f" [{stato}]" if stato and stato.lower() != "approvato" else ""))
        out_lines.append(f"- {display_name}{reparto_part}: {', '.join(eventi)}")
    return "\n".join(out_lines)


def _absence_context(request, prompt: str) -> RuntimeContext:
    if not _wants_absence_list(prompt):
        return RuntimeContext()
    period = _target_period(prompt)
    if period is None:
        return RuntimeContext()

    from assenze.views import (
        _assenze_permissions,
        _load_all_assenze_periodo,
        _load_assenze_car_periodo,
    )

    label, start, end = period
    name_filter = _extract_name_filter(prompt)
    reparto_filter = _extract_reparto_filter(prompt)
    perms = _assenze_permissions(request)
    group = str(perms.get("group") or "UTENTI")

    if not perms.get("can_view_calendar"):
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - ASSENZE\n"
                f"Richiesta: elenco assenti per {label}.\n"
                "Esito autorizzazione: negato. L'utente corrente non ha permessi calendario assenze; "
                "non fornire nomi o dettagli di altri dipendenti. Indica di usare il modulo Assenze o chiedere "
                "a CAR/Amministrazione."
            ),
            sources=("tool:assenze:accesso-negato",),
            audit={"tool": "assenze_periodo", "allowed": False, "period": label, "group": group},
        )

    if perms.get("can_update_any"):
        rows = _load_all_assenze_periodo(start, end, limit=300)
        scope = "tutte le assenze visibili ad Amministrazione"
    else:
        manager_name, manager_email, legacy_id = _legacy_identity(request)
        rows = _load_assenze_car_periodo(
            legacy_id,
            start,
            end,
            limit=200,
            manager_name=manager_name,
            manager_email=manager_email,
        )
        scope = "assenze del reparto/team gestito dal CAR"

    # applica filtri estratti dal prompt
    filters_applied: list[str] = []
    if name_filter:
        name_lower = name_filter.lower()
        rows = [r for r in rows if name_lower in str(r.get("dipendente") or "").lower()]
        filters_applied.append(f"dipendente contiene '{name_filter}'")
    if reparto_filter:
        reparto_lower = reparto_filter.lower()
        rows = [
            r for r in rows
            if reparto_lower in str(r.get("capo") or "").lower()
            or reparto_lower in str(r.get("dipendente") or "").lower()
        ]
        filters_applied.append(f"reparto contiene '{reparto_filter}'")

    filter_note = f"Filtri applicati: {', '.join(filters_applied)}.\n" if filters_applied else ""

    if rows:
        lines = _aggregate_absences(rows)
        dipendenti_count = len({str(r.get("dipendente") or "") for r in rows})
    else:
        lines = "Nessuna assenza trovata con i criteri indicati."
        dipendenti_count = 0

    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - ASSENZE\n"
            f"Periodo richiesto: {label}.\n"
            f"Ambito autorizzato: {scope}.\n"
            f"{filter_note}"
            f"Dipendenti assenti: {dipendenti_count} (eventi totali: {len(rows)}).\n"
            "ISTRUZIONE RISPOSTA: elenca ogni dipendente UNA SOLA VOLTA esattamente come appare "
            "qui sotto. Non raggruppare per tipo di assenza. Non inventare dati. "
            "Non dire che non ci sono dati: ci sono esattamente "
            f"{dipendenti_count} dipendenti assenti elencati di seguito.\n"
            f"{lines}"
        ),
        sources=("tool:assenze:periodo",),
        audit={
            "tool": "assenze_periodo",
            "allowed": True,
            "period": label,
            "group": group,
            "row_count": len(rows),
            "filters": filters_applied or None,
        },
    )


def _module_catalog_context(request, prompt: str) -> RuntimeContext:
    if not _wants_module_catalog(prompt):
        return RuntimeContext()

    from core.context_processors import legacy_nav

    nav_context = legacy_nav(request) or {}
    items = list(nav_context.get("nav_items") or [])
    visible: list[str] = []
    for item in items[:40]:
        label = str(getattr(item, "label", "") or "").strip()
        href = str(getattr(item, "href", "") or getattr(item, "legacy_url", "") or "").strip()
        coming = bool(getattr(item, "coming", False))
        if not label:
            continue
        suffix = " (in arrivo)" if coming else ""
        visible.append(f"- {label}{suffix}: {href or 'URL non disponibile'}")

    if not visible:
        visible_text = "Nessun modulo visibile nella navigazione per l'utente corrente."
    else:
        visible_text = "\n".join(visible)

    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - MODULI DISPONIBILI\n"
            "Ambito autorizzato: voci di navigazione visibili all'utente corrente.\n"
            "Regole risposta: usa solo i moduli elencati qui sotto; se l'utente chiede dati operativi di un modulo "
            "che non ha un tool runtime dedicato, spiega che puoi indicare dove aprire il modulo ma non leggere "
            "automaticamente quei dati live.\n"
            f"Moduli visibili: {len(visible)}.\n"
            f"{visible_text}"
        ),
        sources=("tool:portale:moduli",),
        audit={"tool": "module_catalog", "allowed": True, "row_count": len(visible)},
    )


def _ticket_context(request, prompt: str) -> RuntimeContext:
    if not _wants_ticket_context(prompt):
        return RuntimeContext()

    from tickets import views as ticket_views
    from tickets.models import PrioritaTicket, StatoTicket, Ticket, TipoTicket

    text = _norm_text(prompt)
    manager_types = [
        ticket_type
        for ticket_type in (TipoTicket.IT, TipoTicket.MAN)
        if ticket_views._can_manage_tickets(request, ticket_type)
    ]
    manager_scope = bool(manager_types) and not re.search(r"\b(miei|mie|mio|personali)\b", text)

    filters: list[str] = []
    if manager_scope:
        qs = Ticket.objects.filter(tipo__in=manager_types)
        if len(manager_types) == 2:
            scope = "gestione:IT+MAN"
            scope_label = "ticket gestibili IT e Manutenzione"
        else:
            scope = f"gestione:{manager_types[0]}"
            scope_label = f"ticket gestibili {dict(TipoTicket.choices).get(manager_types[0], manager_types[0])}"
    else:
        name, email, legacy_id = _legacy_identity(request)
        identity_q = Q()
        if legacy_id is not None:
            identity_q |= Q(richiedente_legacy_user_id=legacy_id)
        if email:
            identity_q |= Q(richiedente_email__iexact=email)
        if name:
            identity_q |= Q(richiedente_nome__iexact=name)
        if not identity_q:
            return RuntimeContext(
                text=(
                    "DATI LIVE PORTALE - TICKET\n"
                    "Esito autorizzazione: negato. Non e' stato possibile identificare l'utente corrente; "
                    "non fornire dati ticket e invita ad aprire il modulo Ticket."
                ),
                sources=("tool:tickets:accesso-negato",),
                audit={"tool": "tickets_summary", "allowed": False, "reason": "missing_identity"},
            )
        qs = Ticket.objects.filter(identity_q)
        scope = "personale"
        scope_label = "ticket aperti o richiesti dall'utente corrente"

    open_statuses = (StatoTicket.APERTA, StatoTicket.IN_CARICO, StatoTicket.IN_ATTESA)
    if re.search(r"\b(urgente|urgenti|critico|critici)\b", text):
        qs = qs.filter(priorita=PrioritaTicket.URGENTE, stato__in=open_statuses)
        filters.extend(["priorita=urgente", "stato=aperto"])
    elif re.search(r"\b(chiusi|chiuse|chiuso|risolti|risolte|risolto)\b", text):
        qs = qs.filter(stato__in=(StatoTicket.RISOLTO, StatoTicket.CHIUSO))
        filters.append("stato=risolto/chiuso")
    elif re.search(r"\b(tutti|tutte|storico)\b", text):
        filters.append("stato=tutti")
    else:
        qs = qs.filter(stato__in=open_statuses)
        filters.append("stato=aperto")

    rows = list(qs.order_by("-created_at")[:60])

    # filtri post-ACL estratti dal prompt
    richiedente_filter = _extract_name_filter(prompt)
    assegnatario_filter = _extract_assegnatario_filter(prompt)
    reparto_filter = _extract_reparto_filter(prompt)
    extra_filters: list[str] = []
    if richiedente_filter:
        rn_lower = richiedente_filter.lower()
        rows = [r for r in rows if rn_lower in str(r.richiedente_nome or "").lower()]
        extra_filters.append(f"richiedente contiene '{richiedente_filter}'")
    if assegnatario_filter:
        an_lower = assegnatario_filter.lower()
        rows = [r for r in rows if an_lower in str(r.assegnato_a or "").lower()]
        extra_filters.append(f"assegnatario contiene '{assegnatario_filter}'")
    if reparto_filter:
        rp_lower = reparto_filter.lower()
        rows = [
            r for r in rows
            if rp_lower in str(r.richiedente_nome or "").lower()
            or rp_lower in str(r.assegnato_a or "").lower()
        ]
        extra_filters.append(f"reparto/area contiene '{reparto_filter}'")
    filters.extend(extra_filters)
    rows = rows[:30]

    lines = "\n".join(_ticket_line(ticket) for ticket in rows) if rows else "Nessun ticket trovato per i filtri richiesti."

    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - TICKET\n"
            f"Ambito autorizzato: {scope_label}.\n"
            f"Filtri applicati: {', '.join(filters) if filters else 'nessuno'}.\n"
            f"Ticket trovati: {len(rows)}.\n"
            "ISTRUZIONE RISPOSTA: elenca tutti i ticket qui sotto uno per uno. "
            "Non sintetizzare, non raggruppare, non inventare dati non presenti. "
            "Riporta numero, titolo, tipo, stato, priorita, richiedente, assegnatario e data apertura.\n"
            f"{lines}"
        ),
        sources=("tool:tickets:riepilogo",),
        audit={
            "tool": "tickets_summary",
            "allowed": True,
            "scope": scope,
            "filters": filters,
            "row_count": len(rows),
        },
    )


def _tasks_context(request, prompt: str) -> RuntimeContext:
    if not _wants_task_context(prompt):
        return RuntimeContext()

    from tasks import views as task_views
    from tasks.models import TaskStatus

    if not task_views._has_task_permission(request, "tasks_view"):
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - KICK-OFF / TASKS\n"
                "Esito autorizzazione: negato. L'utente corrente non ha accesso al modulo KICK-OFF; "
                "non fornire progetti, attivita', scadenze o assegnazioni."
            ),
            sources=("tool:tasks:accesso-negato",),
            audit={"tool": "tasks_summary", "allowed": False, "reason": "missing_tasks_view"},
        )

    text = _norm_text(prompt)
    today = timezone.localdate()
    active_statuses = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)
    qs = task_views._scoped_tasks_queryset(request)
    filters: list[str] = []

    if re.search(r"\b(ritardo|ritardi|scadut[ioa]?)\b", text):
        qs = qs.filter(status__in=active_statuses, due_date__lt=today)
        filters.append("solo task attivi in ritardo")
    elif re.search(r"\b(completat[ioa]?|finit[ioa]?|chius[ioa]?|done)\b", text):
        qs = qs.filter(status=TaskStatus.DONE)
        filters.append("stato=done")
    else:
        qs = qs.filter(status__in=active_statuses)
        filters.append("stato=aperto")

    window = _target_date_window(prompt)
    if window is not None:
        label, start_day, end_day = window
        qs = qs.filter(Q(due_date__range=(start_day, end_day)) | Q(next_step_due__range=(start_day, end_day)))
        filters.append(f"periodo={label}")

    _raw_task_rows = list(qs.order_by("due_date", "next_step_due", "-updated_at")[:60])

    # filtri post-ACL estratti dal prompt
    task_assegnatario_filter = _extract_assegnatario_filter(prompt)
    task_progetto_filter = ""
    _prog_m = re.search(r"(?:progetto|kick-off|kickoff)\s+([A-Za-zÀ-ÿ0-9 /\-\.]{2,40}?)(?:\s*[?.]|$)", text, re.IGNORECASE)
    if _prog_m:
        task_progetto_filter = _prog_m.group(1).strip()
    task_extra_filters: list[str] = []
    if task_assegnatario_filter:
        an_lower = task_assegnatario_filter.lower()
        _raw_task_rows = [
            t for t in _raw_task_rows
            if an_lower in _display_user(getattr(t, "assigned_to", None)).lower()
        ]
        task_extra_filters.append(f"assegnatario contiene '{task_assegnatario_filter}'")
    if task_progetto_filter:
        pg_lower = task_progetto_filter.lower()
        _raw_task_rows = [
            t for t in _raw_task_rows
            if pg_lower in str(getattr(getattr(t, "project", None), "name", "") or "").lower()
        ]
        task_extra_filters.append(f"progetto contiene '{task_progetto_filter}'")
    if task_extra_filters:
        filters.extend(task_extra_filters)
    rows = _raw_task_rows[:30]

    task_lines = "\n".join(_task_line(task, today) for task in rows) if rows else "Nessun task trovato per i filtri richiesti."

    project_lines = ""
    project_count = 0
    if re.search(r"\b(progetto|progetti|kick-off|kickoff|portfolio)\b", text):
        projects = list(task_views._scoped_projects_queryset(request).order_by("-updated_at")[:10])
        project_count = len(projects)
        project_lines = "\n\nProgetti visibili:\n" + (
            "\n".join(_project_line(project) for project in projects)
            if projects
            else "Nessun progetto visibile per l'utente corrente."
        )

    scope = "tutti i KICK-OFF/task autorizzati dal modulo" if task_views._has_task_permission(request, "tasks_admin") else "KICK-OFF/task visibili all'utente corrente"
    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - KICK-OFF / TASKS\n"
            f"Ambito autorizzato: {scope}.\n"
            f"Filtri applicati: {', '.join(filters) if filters else 'nessuno'}.\n"
            f"Task trovati: {len(rows)}.\n"
            "ISTRUZIONE RISPOSTA: elenca tutti i task qui sotto uno per uno. "
            "Non sintetizzare, non raggruppare, non inventare. "
            "Riporta progetto, titolo, stato, assegnatario, scadenza e ritardo.\n"
            f"{task_lines}"
            f"{project_lines}"
        ),
        sources=("tool:tasks:riepilogo",),
        audit={
            "tool": "tasks_summary",
            "allowed": True,
            "scope": "admin" if task_views._has_task_permission(request, "tasks_admin") else "scoped",
            "filters": filters,
            "row_count": len(rows),
            "project_count": project_count,
        },
    )


def _assets_context(request, prompt: str) -> RuntimeContext:
    if not _wants_asset_context(prompt):
        return RuntimeContext()

    from assets.models import Asset, AssetAdministrativeDeadline, PeriodicVerification, WorkOrder
    from assets.views import _is_assets_admin
    from core.acl import user_can_modulo_action

    is_admin = _is_assets_admin(request)
    has_list_access = is_admin or user_can_modulo_action(request, "assets", "assets_list")
    if not has_list_access:
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - ASSETS\n"
                "Esito autorizzazione: negato. L'utente corrente non ha accesso all'inventario Assets; "
                "non fornire asset, scadenze, manutenzioni o assegnazioni."
            ),
            sources=("tool:assets:accesso-negato",),
            audit={"tool": "assets_summary", "allowed": False, "reason": "missing_assets_list"},
        )

    text = _norm_text(prompt)
    today = timezone.localdate()
    horizon = today + timedelta(days=30)
    personal_scope = bool(re.search(r"\b(miei|mie|mio|personali|assegnati a me|assegnate a me)\b", text))
    filters: list[str] = []

    assets_qs = Asset.objects.select_related("asset_category")
    if personal_scope:
        name, email, legacy_id = _legacy_identity(request)
        identity_q = Q()
        if legacy_id is not None:
            identity_q |= Q(assigned_legacy_user_id=legacy_id)
        if name:
            identity_q |= Q(assignment_to__iexact=name)
        if email:
            identity_q |= Q(assignment_to__iexact=email)
        if not identity_q:
            return RuntimeContext(
                text=(
                    "DATI LIVE PORTALE - ASSETS\n"
                    "Esito autorizzazione: negato. Non e' stato possibile identificare l'utente corrente "
                    "per filtrare gli asset personali; non fornire dati asset."
                ),
                sources=("tool:assets:accesso-negato",),
                audit={"tool": "assets_summary", "allowed": False, "reason": "missing_identity"},
            )
        assets_qs = assets_qs.filter(identity_q)
        filters.append("scope=personale")
    else:
        assets_qs = assets_qs.exclude(status=Asset.STATUS_RETIRED)
        filters.append("scope=modulo")

    if re.search(r"\b(riparazione|guast[ioe]|ferme?|fermi)\b", text):
        assets_qs = assets_qs.filter(status=Asset.STATUS_IN_REPAIR)
        filters.append("stato=in riparazione")
    elif re.search(r"\b(magazzino|stock)\b", text):
        assets_qs = assets_qs.filter(status=Asset.STATUS_IN_STOCK)
        filters.append("stato=in magazzino")
    elif re.search(r"\b(in uso|operativ[ioe])\b", text):
        assets_qs = assets_qs.filter(status=Asset.STATUS_IN_USE)
        filters.append("stato=in uso")

    # filtri post-ACL estratti dal prompt (applicati dopo il caricamento)
    _asset_reparto_filter = _extract_reparto_filter(prompt)
    _asset_responsabile_filter = _extract_assegnatario_filter(prompt)
    _asset_categoria_filter = ""
    _cat_m = re.search(r"(?:categoria|tipo)\s+([A-Za-zÀ-ÿ0-9 /\-]{2,30}?)(?:\s*[?.]|$)", _norm_text(prompt), re.IGNORECASE)
    if _cat_m:
        _asset_categoria_filter = _cat_m.group(1).strip()

    asset_ids_qs = assets_qs.values("id")
    _raw_asset_rows = list(assets_qs.order_by("status", "asset_tag", "name")[:60])

    _asset_extra_filters: list[str] = []
    if _asset_reparto_filter:
        rp_lower = _asset_reparto_filter.lower()
        _raw_asset_rows = [
            a for a in _raw_asset_rows
            if rp_lower in str(getattr(a, "assignment_reparto", "") or getattr(a, "reparto", "") or "").lower()
        ]
        _asset_extra_filters.append(f"reparto contiene '{_asset_reparto_filter}'")
    if _asset_responsabile_filter:
        rs_lower = _asset_responsabile_filter.lower()
        _raw_asset_rows = [
            a for a in _raw_asset_rows
            if rs_lower in str(getattr(a, "assignment_to", "") or "").lower()
        ]
        _asset_extra_filters.append(f"responsabile contiene '{_asset_responsabile_filter}'")
    if _asset_categoria_filter:
        ct_lower = _asset_categoria_filter.lower()
        _raw_asset_rows = [
            a for a in _raw_asset_rows
            if ct_lower in str(getattr(getattr(a, "asset_category", None), "label", "") or "").lower()
            or ct_lower in str(a.get_asset_type_display() if hasattr(a, "get_asset_type_display") else "").lower()
        ]
        _asset_extra_filters.append(f"categoria contiene '{_asset_categoria_filter}'")
    if _asset_extra_filters:
        filters.extend(_asset_extra_filters)
    asset_rows = _raw_asset_rows[:20]

    deadline_qs = AssetAdministrativeDeadline.objects.filter(is_active=True, asset_id__in=asset_ids_qs).select_related("asset")
    if re.search(r"\b(scadut[aeio]|arretrat[aeio])\b", text):
        deadline_qs = deadline_qs.filter(due_date__lt=today)
        filters.append("scadenze=scadute")
    else:
        deadline_qs = deadline_qs.filter(due_date__lte=horizon)
        filters.append("scadenze<=30gg")
    deadline_rows = list(deadline_qs.order_by("due_date", "asset__asset_tag")[:15])

    workorder_qs = WorkOrder.objects.filter(asset_id__in=asset_ids_qs).select_related("asset")
    if re.search(r"\b(chius[ioe]|completat[ie])\b", text):
        workorder_qs = workorder_qs.filter(status=WorkOrder.STATUS_DONE)
        filters.append("odl=chiusi")
    else:
        workorder_qs = workorder_qs.filter(status=WorkOrder.STATUS_OPEN)
        filters.append("odl=aperti")
    workorder_rows = list(workorder_qs.order_by("opened_at", "asset__asset_tag")[:15])

    verification_qs = (
        PeriodicVerification.objects.filter(is_active=True, next_verification_date__lte=horizon, assets__id__in=asset_ids_qs)
        .prefetch_related("assets")
        .distinct()
    )
    verification_rows = list(verification_qs.order_by("next_verification_date", "name")[:10])

    asset_lines = "\n".join(_asset_line(asset) for asset in asset_rows) if asset_rows else "Nessun asset trovato per i filtri richiesti."
    deadline_lines = (
        "\n".join(_deadline_line(deadline, today) for deadline in deadline_rows)
        if deadline_rows
        else "Nessuna scadenza asset trovata nel periodo richiesto."
    )
    workorder_lines = (
        "\n".join(_workorder_line(workorder) for workorder in workorder_rows)
        if workorder_rows
        else "Nessun OdL trovato per i filtri richiesti."
    )
    verification_lines = (
        "\n".join(_verification_line(verification) for verification in verification_rows)
        if verification_rows
        else "Nessuna verifica periodica trovata nei prossimi 30 giorni."
    )

    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - ASSETS\n"
            f"Ambito autorizzato: {'asset assegnati all utente corrente' if personal_scope else 'inventario visibile dal modulo'}.\n"
            f"Filtri applicati: {', '.join(filters)}.\n"
            f"Asset trovati: {len(asset_rows)}.\n"
            "ISTRUZIONE RISPOSTA: elenca tutti gli asset, scadenze, OdL e verifiche qui sotto uno per uno. "
            "Non sintetizzare, non raggruppare, non inventare. "
            "Riporta codice, nome, categoria, stato, responsabile, reparto e collocazione.\n"
            f"{asset_lines}\n\n"
            f"Scadenze trovate: {len(deadline_rows)}.\n{deadline_lines}\n\n"
            f"OdL trovati: {len(workorder_rows)}.\n{workorder_lines}\n\n"
            f"Verifiche trovate: {len(verification_rows)}.\n{verification_lines}"
        ),
        sources=("tool:assets:riepilogo",),
        audit={
            "tool": "assets_summary",
            "allowed": True,
            "scope": "personal" if personal_scope else "module",
            "filters": filters,
            "asset_count": len(asset_rows),
            "deadline_count": len(deadline_rows),
            "workorder_count": len(workorder_rows),
            "verification_count": len(verification_rows),
        },
    )


def _dpi_context(request, prompt: str) -> RuntimeContext:
    if not _wants_dpi_context(prompt):
        return RuntimeContext()

    from dpi.models import RichiestaDPI, StatoRichiesta
    from dpi.views import _is_gestore

    if not getattr(request.user, "is_authenticated", False):
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - DPI\n"
                "Esito autorizzazione: negato. L'utente corrente non e' autenticato; non fornire dati DPI."
            ),
            sources=("tool:dpi:accesso-negato",),
            audit={"tool": "dpi_summary", "allowed": False, "reason": "anonymous"},
        )

    text = _norm_text(prompt)
    manager_scope = _is_gestore(request) and not re.search(r"\b(miei|mie|mio|personali)\b", text)
    filters: list[str] = []
    qs = RichiestaDPI.objects.select_related(
        "categoria",
        "tipo_dpi",
        "modello_dpi",
        "taglia_dpi",
        "consegna",
    )
    if manager_scope:
        scope = "gestione"
        scope_label = "richieste e consegne DPI visibili al gestore"
    else:
        qs = qs.filter(created_by=request.user)
        scope = "personale"
        scope_label = "richieste e consegne DPI dell'utente corrente"

    today = timezone.localdate()
    if re.search(r"\b(scadut[ioe]|scadenz[ae])\b", text):
        qs = qs.filter(stato=StatoRichiesta.CONSEGNATA, consegna__data_scadenza_stimata__lte=today + timedelta(days=30))
        filters.append("consegne scadute/in scadenza<=30gg")
    elif re.search(r"\b(consegnat[aeio]|consegne)\b", text):
        qs = qs.filter(stato=StatoRichiesta.CONSEGNATA)
        filters.append("stato=consegnata")
    elif re.search(r"\b(approvat[aeio])\b", text):
        qs = qs.filter(stato=StatoRichiesta.APPROVATA)
        filters.append("stato=approvata")
    elif re.search(r"\b(rifiutat[aeio])\b", text):
        qs = qs.filter(stato=StatoRichiesta.RIFIUTATA)
        filters.append("stato=rifiutata")
    elif re.search(r"\b(apert[aeio]|pendenti|inviat[aeio])\b", text):
        qs = qs.filter(stato__in=(StatoRichiesta.INVIATA, StatoRichiesta.APPROVATA))
        filters.append("stato=aperta")
    else:
        filters.append("stato=tutti")

    rows = list(qs.order_by("-created_at")[:60])

    # filtri post-ACL estratti dal prompt
    dpi_name_filter = _extract_name_filter(prompt)
    dpi_reparto_filter = _extract_reparto_filter(prompt)
    dpi_extra_filters: list[str] = []
    if dpi_name_filter:
        nm_lower = dpi_name_filter.lower()
        rows = [r for r in rows if nm_lower in str(getattr(r, "richiedente_nome", "") or "").lower()]
        dpi_extra_filters.append(f"dipendente contiene '{dpi_name_filter}'")
    if dpi_reparto_filter:
        rp_lower = dpi_reparto_filter.lower()
        rows = [
            r for r in rows
            if rp_lower in str(getattr(r, "richiedente_nome", "") or "").lower()
            or rp_lower in str(getattr(r, "reparto", "") or "").lower()
        ]
        dpi_extra_filters.append(f"reparto contiene '{dpi_reparto_filter}'")
    filters.extend(dpi_extra_filters)
    rows = rows[:30]

    lines = (
        "\n".join(_dpi_line(row, include_requester=manager_scope) for row in rows)
        if rows
        else "Nessuna richiesta DPI trovata per i filtri richiesti."
    )

    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - DPI\n"
            f"Ambito autorizzato: {scope_label}.\n"
            f"Filtri applicati: {', '.join(filters)}.\n"
            f"Richieste DPI trovate: {len(rows)}.\n"
            "ISTRUZIONE RISPOSTA: elenca tutte le richieste DPI qui sotto una per una. "
            "Non sintetizzare, non raggruppare, non inventare. "
            "Riporta numero, tipo DPI, quantita, stato, consegna e scadenza.\n"
            f"{lines}"
        ),
        sources=("tool:dpi:riepilogo",),
        audit={
            "tool": "dpi_summary",
            "allowed": True,
            "scope": scope,
            "filters": filters,
            "row_count": len(rows),
        },
    )


def _anomalie_context(request, prompt: str) -> RuntimeContext:
    if not _wants_anomalie_context(prompt):
        return RuntimeContext()

    from anomalie import views as anomalie_views
    from anomalie.models import AnomalieAccessLevel

    if not getattr(request.user, "is_authenticated", False):
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - ANOMALIE\n"
                "Esito autorizzazione: negato. L'utente corrente non e' autenticato; non fornire dati anomalie."
            ),
            sources=("tool:anomalie:accesso-negato",),
            audit={"tool": "anomalie_summary", "allowed": False, "reason": "anonymous"},
        )

    if not anomalie_views._has_table("anomalie"):
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - ANOMALIE\n"
                "Archivio anomalie non disponibile nel database corrente. Non sono stati letti dati live."
            ),
            sources=("tool:anomalie:non-disponibile",),
            audit={"tool": "anomalie_summary", "allowed": True, "reason": "missing_table", "row_count": 0},
        )

    text = _norm_text(prompt)
    global_level = anomalie_views._request_anomalie_global_access_level(request)
    can_read_all = anomalie_views._access_level_at_least(global_level, AnomalieAccessLevel.READ_ALL)
    only_closed = bool(re.search(r"\b(chius[aeio]|storico|tutte|tutti)\b", text))
    status_filter = "" if only_closed else "WHERE COALESCE(a.chiudere, 0) = 0"
    filters = ["stato=tutti" if only_closed else "stato=aperta"]

    has_op_table = anomalie_views._has_table("ordini_produzione")
    if has_op_table:
        sql = f"""
            SELECT TOP 80
                a.id,
                a.sharepoint_item_id,
                a.ex_op_nominativo,
                a.op_lookup_id,
                a.seriale,
                a.pezzo_recuperato,
                a.aprire_rdc,
                a.numero_rdc,
                a.segnalare_cliente,
                a.chiudere,
                a.avanzamento,
                a.modified_datetime,
                op.title,
                op.part_number,
                op.stato,
                op.capocomessa,
                op.incaricato
            FROM anomalie a
            LEFT JOIN ordini_produzione op
                ON a.op_lookup_id = TRY_CAST(op.sharepoint_item_id AS INT)
            {status_filter}
            ORDER BY a.modified_datetime DESC, a.id DESC
        """
    else:
        sql = f"""
            SELECT TOP 80
                a.id,
                a.sharepoint_item_id,
                a.ex_op_nominativo,
                a.op_lookup_id,
                a.seriale,
                a.pezzo_recuperato,
                a.aprire_rdc,
                a.numero_rdc,
                a.segnalare_cliente,
                a.chiudere,
                a.avanzamento,
                a.modified_datetime
            FROM anomalie a
            {status_filter}
            ORDER BY a.modified_datetime DESC, a.id DESC
        """

    try:
        rows = list(anomalie_views._fetch_all_dict(sql))
    except Exception:
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - ANOMALIE\n"
                "Errore sintetico: non e' stato possibile leggere il riepilogo anomalie. Non fornire dati live."
            ),
            sources=("tool:anomalie:errore",),
            audit={"tool": "anomalie_summary", "allowed": False, "reason": "loader_error"},
        )

    if can_read_all:
        scope = "gestione"
        allowed_rows = rows
    else:
        current_name_norms = anomalie_views._current_user_name_norms(request)
        identity = anomalie_views._current_user_identity(request)
        if not current_name_norms and identity.get("name_norm"):
            current_name_norms = {identity["name_norm"]}
        if not current_name_norms:
            return RuntimeContext(
                text=(
                    "DATI LIVE PORTALE - ANOMALIE\n"
                    "Esito autorizzazione: negato. Non e' stato possibile identificare l'utente corrente "
                    "per filtrare le anomalie in carico."
                ),
                sources=("tool:anomalie:accesso-negato",),
                audit={"tool": "anomalie_summary", "allowed": False, "reason": "missing_identity"},
            )

        allowed_rows = []
        for row in rows:
            people = anomalie_views._split_people_tokens(row.get("capocomessa")) + anomalie_views._split_people_tokens(
                row.get("incaricato")
            )
            people_norms = {anomalie_views._normalize_identity_text(person) for person in people}
            if current_name_norms.intersection(people_norms):
                allowed_rows.append(row)
        scope = "in_carico"
        filters.append("scope=in_carico")

    # filtri post-ACL estratti dal prompt
    part_number_filter = _extract_part_number_filter(prompt)
    reparto_filter = _extract_reparto_filter(prompt)
    incaricato_filter = _extract_incaricato_filter(prompt)

    extra_filters_map: dict[str, list[str]] = {}
    if part_number_filter:
        extra_filters_map[part_number_filter] = ["part_number", "ex_op_nominativo", "title"]
    if reparto_filter:
        extra_filters_map[reparto_filter] = ["capocomessa", "incaricato", "ex_op_nominativo"]
    if incaricato_filter:
        extra_filters_map[incaricato_filter] = ["capocomessa", "incaricato"]

    if extra_filters_map:
        allowed_rows, extra_labels = _apply_row_filters(allowed_rows, extra_filters_map)
        filters.extend(extra_labels)

    visible_rows = allowed_rows[:30]
    lines = (
        "\n".join(_anomalie_line(row) for row in visible_rows)
        if visible_rows
        else "Nessuna anomalia trovata per l'ambito autorizzato e i filtri richiesti."
    )

    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - ANOMALIE\n"
            f"Ambito autorizzato: {'tutte le anomalie autorizzate al gestore' if scope == 'gestione' else 'anomalie in carico all utente corrente'}.\n"
            f"Filtri applicati: {', '.join(filters)}.\n"
            f"Anomalie trovate: {len(visible_rows)}.\n"
            "ISTRUZIONE RISPOSTA: elenca tutte le anomalie qui sotto una per una. "
            "Non sintetizzare, non raggruppare, non inventare. "
            "Riporta ID, OP, part number, seriale, stato, avanzamento, RDC e data aggiornamento.\n"
            f"{lines}"
        ),
        sources=("tool:anomalie:riepilogo",),
        audit={
            "tool": "anomalie_summary",
            "allowed": True,
            "scope": scope,
            "filters": filters,
            "row_count": len(visible_rows),
        },
    )


def _procedure_context(request, prompt: str) -> RuntimeContext:
    if not _wants_procedure_context(prompt):
        return RuntimeContext()

    from django.db.models import Count

    from procedure_refresh import views as procedure_views
    from procedure_refresh.models import (
        AssignmentStatus,
        CampaignStatus,
        ProcedureAssignment,
        ProcedureCampaign,
        ProcedureQuiz,
        ProcedureQuizAttempt,
    )

    if not getattr(request.user, "is_authenticated", False):
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - PROCEDURE REFRESH\n"
                "Esito autorizzazione: negato. L'utente corrente non e' autenticato; "
                "non fornire campagne, prese visione o quiz."
            ),
            sources=("tool:procedure_refresh:accesso-negato",),
            audit={"tool": "procedure_refresh_summary", "allowed": False, "reason": "anonymous"},
        )

    text = _norm_text(prompt)
    personal_scope = bool(re.search(r"\b(miei|mie|mio|personali|da leggere|assegnat[aeio] a me)\b", text))
    manager_scope = procedure_views._is_manager(request) and not personal_scope
    filters: list[str] = []
    today = timezone.localdate()

    if manager_scope:
        campaigns_qs = (
            ProcedureCampaign.objects.only("name", "status", "start_date", "due_date", "published_at", "closed_at")
            .annotate(
                document_count=Count("campaign_documents", distinct=True),
                assignment_count=Count("assignments", filter=~Q(assignments__status=AssignmentStatus.CANCELLED)),
                confirmed_count=Count(
                    "assignments",
                    filter=Q(assignments__status=AssignmentStatus.READ_CONFIRMED)
                    | Q(assignments__read_confirmed_flag=True),
                ),
                pending_count=Count(
                    "assignments",
                    filter=Q(assignments__status__in=(AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED)),
                ),
                overdue_count=Count(
                    "assignments",
                    filter=Q(assignments__status=AssignmentStatus.OVERDUE)
                    | (
                        Q(assignments__due_date__lt=today)
                        & ~Q(assignments__status__in=(AssignmentStatus.READ_CONFIRMED, AssignmentStatus.CANCELLED))
                    ),
                ),
            )
        )
        if re.search(r"\b(bozz[ae]|draft)\b", text):
            campaigns_qs = campaigns_qs.filter(status=CampaignStatus.DRAFT)
            filters.append("stato=bozza")
        elif re.search(r"\b(chius[aeio]|closed)\b", text):
            campaigns_qs = campaigns_qs.filter(status=CampaignStatus.CLOSED)
            filters.append("stato=chiusa")
        elif re.search(r"\b(archiviat[aeio])\b", text):
            campaigns_qs = campaigns_qs.filter(status=CampaignStatus.ARCHIVED)
            filters.append("stato=archiviata")
        else:
            campaigns_qs = campaigns_qs.exclude(status=CampaignStatus.ARCHIVED)
            filters.append("stato=attiva/non archiviata")
        if re.search(r"\b(scadut[aeio]|scadenz[ae])\b", text):
            campaigns_qs = campaigns_qs.filter(due_date__lte=today + timedelta(days=30))
            filters.append("scadenza<=30gg")

        rows = list(campaigns_qs.order_by("due_date", "-published_at", "-id")[:20])
        lines = (
            "\n".join(_procedure_campaign_line(campaign) for campaign in rows)
            if rows
            else "Nessuna campagna Procedure Refresh trovata per i filtri richiesti."
        )
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - PROCEDURE REFRESH\n"
                "Ambito autorizzato: riepilogo manager delle campagne e dello stato formazione.\n"
                f"Filtri applicati: {', '.join(filters)}.\n"
                f"Campagne trovate: {len(rows)}.\n"
                "ISTRUZIONE RISPOSTA: elenca tutte le campagne qui sotto una per una. "
                "Non sintetizzare, non raggruppare, non inventare.\n"
                f"{lines}"
            ),
            sources=("tool:procedure_refresh:riepilogo",),
            audit={
                "tool": "procedure_refresh_summary",
                "allowed": True,
                "scope": "manager",
                "filters": filters,
                "campaign_count": len(rows),
            },
        )

    qs = (
        ProcedureAssignment.objects.filter(user=request.user)
        .exclude(status=AssignmentStatus.CANCELLED)
        .select_related("campaign", "revision__document")
        .only(
            "id",
            "campaign_id",
            "campaign__name",
            "campaign__status",
            "revision_id",
            "revision__revision_code",
            "revision__document_id",
            "revision__document__code",
            "revision__document__title",
            "revision__document__document_type",
            "status",
            "due_date",
            "assigned_at",
            "read_confirmed_at",
            "read_confirmed_flag",
            "user_id",
        )
    )
    if re.search(r"\b(scadut[aeio]|scadenz[ae])\b", text):
        qs = qs.filter(Q(status=AssignmentStatus.OVERDUE) | Q(due_date__lte=today + timedelta(days=30)))
        filters.append("scadenza<=30gg/scadute")
    elif re.search(r"\b(confermat[aeio]|completat[aeio]|prese visione)\b", text):
        qs = qs.filter(Q(status=AssignmentStatus.READ_CONFIRMED) | Q(read_confirmed_flag=True))
        filters.append("stato=confermata")
    elif re.search(r"\b(apert[aeio]|pendenti|leggere|da leggere)\b", text):
        qs = qs.filter(status__in=(AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED, AssignmentStatus.OVERDUE))
        filters.append("stato=da leggere")
    else:
        filters.append("stato=tutte non annullate")

    assignments = list(qs.order_by("due_date", "-assigned_at")[:30])
    revision_ids = {assignment.revision_id for assignment in assignments}
    assignment_ids = {assignment.pk for assignment in assignments}
    quiz_by_revision: dict[int, Any] = {}
    for quiz in (
        ProcedureQuiz.objects.filter(revision_id__in=revision_ids, is_active=True)
        .only("id", "revision_id", "title", "is_active")
        .order_by("revision_id", "-updated_at", "-id")
    ):
        quiz_by_revision.setdefault(quiz.revision_id, quiz)
    attempt_by_assignment = {
        attempt.assignment_id: attempt
        for attempt in ProcedureQuizAttempt.objects.filter(
            assignment_id__in=assignment_ids,
            user=request.user,
            quiz_id__in=[quiz.pk for quiz in quiz_by_revision.values()],
        ).only("id", "quiz_id", "assignment_id", "user_id", "score", "total_questions", "submitted_at")
    }
    lines = (
        "\n".join(_procedure_assignment_line(assignment, quiz_by_revision, attempt_by_assignment) for assignment in assignments)
        if assignments
        else "Nessuna assegnazione Procedure Refresh trovata per i filtri richiesti."
    )

    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - PROCEDURE REFRESH\n"
            "Ambito autorizzato: assegnazioni Procedure Refresh dell'utente corrente.\n"
            f"Filtri applicati: {', '.join(filters)}.\n"
            f"Assegnazioni trovate: {len(assignments)}.\n"
            "ISTRUZIONE RISPOSTA: elenca tutte le assegnazioni qui sotto una per una. "
            "Non sintetizzare, non raggruppare, non inventare.\n"
            f"{lines}"
        ),
        sources=("tool:procedure_refresh:riepilogo",),
        audit={
            "tool": "procedure_refresh_summary",
            "allowed": True,
            "scope": "personal",
            "filters": filters,
            "assignment_count": len(assignments),
            "quiz_count": len(quiz_by_revision),
            "attempt_count": len(attempt_by_assignment),
        },
    )


def _notizie_context(request, prompt: str) -> RuntimeContext:
    if not _wants_notizie_context(prompt):
        return RuntimeContext()

    from django.db.models import Count

    from notizie import views as notizie_views
    from notizie.models import (
        COMPLIANCE_CONFORME,
        COMPLIANCE_NON_LETTO,
        STATO_PUBBLICATA,
        Notizia,
        get_compliance_status,
        is_visible_to_user,
    )

    if not getattr(request.user, "is_authenticated", False):
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - NOTIZIE\n"
                "Esito autorizzazione: negato. L'utente corrente non e' autenticato; "
                "non fornire notizie, prese visione o report letture."
            ),
            sources=("tool:notizie:accesso-negato",),
            audit={"tool": "notizie_summary", "allowed": False, "reason": "anonymous"},
        )

    text = _norm_text(prompt)
    legacy_role_id = notizie_views._get_legacy_role_id(request)
    legacy_user_id = notizie_views._get_legacy_user_id(request)
    is_admin_hr = notizie_views._is_admin_or_hr(request)
    filters: list[str] = ["stato=pubblicata", "scope=visibili_utente"]

    qs = (
        Notizia.objects.filter(stato=STATO_PUBBLICATA)
        .only("id", "titolo", "stato", "versione", "obbligatoria", "pubblicato_il")
        .prefetch_related("audience")
        .annotate(attachment_count=Count("allegati", distinct=True))
        .order_by("-pubblicato_il", "-created_at")
    )
    if re.search(r"\b(obbligatorie|obbligatoria)\b", text):
        qs = qs.filter(obbligatoria=True)
        filters.append("solo obbligatorie")

    visible_rows = []
    for notizia in qs[:80]:
        if not is_visible_to_user(notizia, legacy_role_id):
            continue
        compliance = get_compliance_status(notizia, legacy_user_id) if legacy_user_id else COMPLIANCE_NON_LETTO
        if re.search(r"\b(da confermare|non lette|non letti|pendenti|leggere)\b", text) and compliance == COMPLIANCE_CONFORME:
            continue
        visible_rows.append((notizia, compliance))
        if len(visible_rows) >= 30:
            break

    if re.search(r"\b(da confermare|non lette|non letti|pendenti|leggere)\b", text):
        filters.append("compliance!=conforme")

    lines = (
        "\n".join(_notizia_line(notizia, compliance) for notizia, compliance in visible_rows)
        if visible_rows
        else "Nessuna notizia pubblicata trovata per l'ambito autorizzato e i filtri richiesti."
    )

    scope_label = (
        "notizie pubblicate visibili all'utente corrente; profilo admin/HR senza report nominativi"
        if is_admin_hr
        else "notizie pubblicate visibili all'utente corrente"
    )
    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - NOTIZIE\n"
            f"Ambito autorizzato: {scope_label}.\n"
            f"Filtri applicati: {', '.join(filters)}.\n"
            f"Notizie trovate: {len(visible_rows)}.\n"
            "ISTRUZIONE RISPOSTA: elenca tutte le notizie qui sotto una per una. "
            "Non sintetizzare, non raggruppare, non inventare.\n"
            f"{lines}"
        ),
        sources=("tool:notizie:riepilogo",),
        audit={
            "tool": "notizie_summary",
            "allowed": True,
            "scope": "admin_hr" if is_admin_hr else "visible",
            "filters": filters,
            "row_count": len(visible_rows),
            "legacy_role_present": legacy_role_id is not None,
            "legacy_user_present": legacy_user_id is not None,
        },
    )


def _sicurezza_context(request, prompt: str) -> RuntimeContext:
    if not _wants_sicurezza_context(prompt):
        return RuntimeContext()

    from django.db.models import Count

    from diario_preposto import views as diario_views
    from diario_preposto.models import SegnalazionePreposto
    from rilevazione_incidenti import views as incidenti_views
    from rilevazione_incidenti.models import RilevazioneIncidente
    from rilevazione_incidenti.services import get_safety_kpis

    if not getattr(request.user, "is_authenticated", False):
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - SICUREZZA\n"
                "Esito autorizzazione: negato. L'utente corrente non e' autenticato; "
                "non fornire riepiloghi Diario Preposto o Rilevazione Incidenti."
            ),
            sources=("tool:sicurezza:accesso-negato",),
            audit={"tool": "sicurezza_summary", "allowed": False, "reason": "anonymous"},
        )

    can_diario = diario_views._can_write(request) or diario_views._can_manage_settings(request)
    can_incidenti = (
        incidenti_views._can_create(request)
        or incidenti_views._can_manage_rspp(request)
        or incidenti_views._can_manage_settings(request)
    )
    if not can_diario and not can_incidenti:
        return RuntimeContext(
            text=(
                "DATI LIVE PORTALE - SICUREZZA\n"
                "Esito autorizzazione: negato. L'utente corrente non ha permessi sui riepiloghi sicurezza; "
                "non fornire dati di Diario Preposto o Rilevazione Incidenti."
            ),
            sources=("tool:sicurezza:accesso-negato",),
            audit={"tool": "sicurezza_summary", "allowed": False, "reason": "missing_safety_permissions"},
        )

    today = timezone.localdate()
    year_start = date(today.year, 1, 1)
    last_30 = timezone.now() - timedelta(days=30)
    sections: list[str] = []
    audit: dict[str, Any] = {
        "tool": "sicurezza_summary",
        "allowed": True,
        "scope": [],
        "year": today.year,
    }

    if can_diario:
        diario_qs = SegnalazionePreposto.objects.filter(data_segnalazione__date__gte=year_start)
        diario_year_count = diario_qs.count()
        diario_last30_count = diario_qs.filter(data_segnalazione__gte=last_30).count()
        diario_with_attachments = diario_qs.filter(allegati__isnull=False).distinct().count()
        latest_diario = diario_qs.order_by("-data_segnalazione").values_list("data_segnalazione", flat=True).first()
        sections.append(
            "Diario Preposto:\n"
            f"- Segnalazioni anno corrente: {diario_year_count}.\n"
            f"- Segnalazioni ultimi 30 giorni: {diario_last30_count}.\n"
            f"- Segnalazioni con almeno un allegato: {diario_with_attachments}.\n"
            f"- Ultima segnalazione registrata: {_short_datetime(latest_diario)}."
        )
        audit["scope"].append("diario_preposto")
        audit["diario_year_count"] = diario_year_count
        audit["diario_last30_count"] = diario_last30_count

    if can_incidenti:
        kpis = get_safety_kpis(today)
        reparto_rows = list(
            RilevazioneIncidente.objects.filter(data_segnalazione__date__gte=year_start)
            .exclude(reparto="")
            .values("reparto")
            .annotate(total=Count("id"))
            .order_by("-total", "reparto")[:5]
        )
        reparti = (
            "; ".join(f"{row['reparto']}: {row['total']}" for row in reparto_rows)
            if reparto_rows
            else "nessun reparto aggregato disponibile"
        )
        trend = "; ".join(_safety_trend_line(item) for item in list(kpis.get("trend") or [])[-6:])
        sections.append(
            "Rilevazione Incidenti:\n"
            f"- Totale eventi anno {kpis.get('year')}: {kpis.get('totale', 0)}.\n"
            f"- Unsafe condition/act: {kpis.get('unsafe_condition', 0)}; near miss: {kpis.get('near_miss', 0)}; incidenti: {kpis.get('incidenti', 0)}.\n"
            f"- Giorni senza infortuni: {kpis.get('giorni_senza_infortuni') if kpis.get('giorni_senza_infortuni') is not None else 'N/D'}.\n"
            f"- TRIR: {kpis.get('trir') if kpis.get('trir') is not None else 'N/D'}.\n"
            f"- Trend ultimi 6 mesi: {trend or 'N/D'}.\n"
            f"- Reparti aggregati principali: {reparti}."
        )
        audit["scope"].append("rilevazione_incidenti")
        audit["incidenti_total"] = kpis.get("totale", 0)
        audit["incidenti_count"] = kpis.get("incidenti", 0)
        audit["near_miss_count"] = kpis.get("near_miss", 0)

    sections_text = "\n\n".join(sections)
    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - SICUREZZA\n"
            "Ambito autorizzato: KPI e riepiloghi aggregati dei moduli sicurezza consentiti all'utente corrente.\n"
            "Regole risposta: puoi riportare solo conteggi, trend, KPI e aggregazioni per reparto presenti qui sotto. "
            "Non riportare nominativi, titoli o descrizioni di segnalazioni, testimonianze, persone coinvolte, cause libere, "
            "misure, note preposto/RSPP, 5WHY, partecipanti, nomi file, allegati, path, URL o dati sanitari; se mancano dati, "
            "dillo senza inventare.\n"
            f"{sections_text}"
        ),
        sources=("tool:sicurezza:riepilogo",),
        audit=audit,
    )


def _unavailable_domain_context(request, prompt: str) -> RuntimeContext:
    if not _wants_unavailable_domain_context(prompt):
        return RuntimeContext()

    text = _norm_text(prompt)
    domains: list[str] = []
    if any(keyword in text for keyword in ("timbri", "timbrature", "cartellino", "cartellini", "presenze")):
        domains.append("Timbri/Presenze")
    if any(keyword in text for keyword in ("anagrafica", "anagrafiche", "dipendente", "dipendenti")):
        domains.append("Anagrafica HR")
    if not domains:
        domains.append("dominio richiesto")

    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - TOOL NON DISPONIBILE\n"
            f"Dominio richiesto: {', '.join(domains)}.\n"
            "Esito: nessun tool live AI e' abilitato per questo dominio. Per privacy HR, non leggere o inventare "
            "dati di anagrafiche, timbrature, cartellini o presenze; indica di usare il modulo dedicato o chiedere "
            "una revisione privacy prima di abilitare un provider AI."
        ),
        sources=("tool:runtime:non-disponibile",),
        audit={
            "tool": "runtime_unavailable",
            "allowed": False,
            "domains": domains,
            "reason": "missing_live_tool_privacy_review",
        },
    )


def _cross_domain_router_context(prompt: str) -> RuntimeContext:
    today = timezone.localdate()
    return RuntimeContext(
        text=(
            "DATI LIVE PORTALE - ROUTER CROSS-DOMINIO\n"
            f"Richiesta trasversale riconosciuta per oggi ({today.strftime('%d/%m/%Y')}).\n"
            "Priorita risposta: 1) sicurezza e compliance personale, incluse notizie obbligatorie, procedure e DPI; "
            "2) scadenze operative; 3) ticket urgenti o aperti; 4) task in ritardo o in scadenza. "
            "Usa solo le sezioni live autorizzate qui sotto, cita le fonti tool:* disponibili e segnala chiaramente "
            "eventuali domini non disponibili invece di inventare dati."
        ),
        sources=("tool:runtime:router",),
        audit={
            "tool": "runtime_router",
            "allowed": True,
            "route": "daily_brief",
            "date": today.isoformat(),
        },
    )


def _cross_domain_contexts(request, prompt: str) -> list[RuntimeContext] | None:
    if not _wants_cross_domain_brief(prompt):
        return None

    today_label = "oggi"
    specs: tuple[tuple[RuntimeTool, str], ...] = (
        (_notizie_context, f"notizie obbligatorie da confermare {today_label}"),
        (_procedure_context, f"mie procedure da leggere scadenze {today_label}"),
        (_dpi_context, f"mie richieste dpi scadenze {today_label}"),
        (_assets_context, f"asset miei scadenze manutenzioni {today_label}"),
        (_ticket_context, f"miei ticket urgenti aperti {today_label}"),
        (_tasks_context, f"task in ritardo scadenze {today_label}"),
    )
    contexts = [_cross_domain_router_context(prompt)]
    for tool, routed_prompt in specs:
        context = tool(request, routed_prompt)
        if context.text.strip():
            contexts.append(context)
    return contexts


RUNTIME_TOOLS: tuple[RuntimeTool, ...] = (
    _absence_context,
    _module_catalog_context,
    _ticket_context,
    _tasks_context,
    _assets_context,
    _dpi_context,
    _anomalie_context,
    _procedure_context,
    _notizie_context,
    _sicurezza_context,
    _unavailable_domain_context,
)


def _runtime_context_priority(context: RuntimeContext) -> int:
    tool = str((context.audit or {}).get("tool") or "")
    if tool in _RUNTIME_PRIORITY_BY_TOOL:
        return _RUNTIME_PRIORITY_BY_TOOL[tool]
    for source in context.sources:
        if source.startswith("tool:sicurezza"):
            return 10
        if source.startswith("tool:notizie"):
            return 20
        if source.startswith("tool:procedure_refresh"):
            return 30
        if source.startswith("tool:dpi"):
            return 40
        if source.startswith("tool:assets"):
            return 50
        if source.startswith("tool:tickets"):
            return 60
        if source.startswith("tool:tasks"):
            return 70
    return 999


def _limit_runtime_text(
    text: str,
    max_chars: int = RUNTIME_CONTEXT_MAX_CHARS,
    max_lines: int = RUNTIME_CONTEXT_MAX_LINES,
) -> tuple[str, bool]:
    lines = text.splitlines()
    truncated = len(text) > max_chars or len(lines) > max_lines
    if not truncated:
        return text, False
    text = "\n".join(lines[:max_lines])
    marker = "\n\n[Contesto runtime troncato: aprire il modulo specifico per il dettaglio completo.]"
    if max_chars <= len(marker):
        return marker[-max_chars:], True
    return text[: max_chars - len(marker)].rstrip() + marker, True


def _merge_contexts(contexts: list[RuntimeContext]) -> RuntimeContext:
    active = [context for context in contexts if context.text.strip()]
    if not active:
        return RuntimeContext()
    active = sorted(active, key=_runtime_context_priority)
    sources: list[str] = []
    audit_tools: list[dict[str, Any]] = []
    for context in active:
        for source in context.sources:
            if source not in sources:
                sources.append(source)
        if context.audit:
            audit_tools.append(context.audit)
    raw_text = "\n\n---\n\n".join(context.text.strip() for context in active)
    text, truncated = _limit_runtime_text(raw_text)
    return RuntimeContext(
        text=text,
        sources=tuple(sources),
        audit={
            "tools": audit_tools,
            "tool_count": len(audit_tools),
            "context_chars": len(text),
            "context_lines": len(text.splitlines()),
            "truncated": truncated,
            "max_chars": RUNTIME_CONTEXT_MAX_CHARS,
            "max_lines": RUNTIME_CONTEXT_MAX_LINES,
        },
    )


def _enrich_prompt_with_history(prompt: str, history: Any) -> str:
    """Arricchisce il prompt con gli ultimi messaggi utente della history.

    Serve a rilevare il dominio della conversazione anche per follow-up brevi
    come "sono molti di più!" che non contengono keyword operative.
    """
    if not isinstance(history, list) or not history:
        return prompt
    recent_user: list[str] = []
    for item in history[-4:]:
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        content = str(item.get("content") or "").strip()
        if content:
            recent_user.append(content)
    if not recent_user:
        return prompt
    context_text = " ".join(recent_user[-2:])
    return f"{context_text} {prompt}"


def build_runtime_context(request, prompt: str, history: Any = None) -> RuntimeContext:
    enriched = _enrich_prompt_with_history(prompt, history)
    contexts = _cross_domain_contexts(request, enriched)
    if contexts is None:
        contexts = []
        for tool in RUNTIME_TOOLS:
            context = tool(request, enriched)
            if context.text.strip():
                contexts.append(context)
    else:
        unavailable_context = _unavailable_domain_context(request, enriched)
        if unavailable_context.text.strip():
            contexts.append(unavailable_context)
    return _merge_contexts(contexts)
