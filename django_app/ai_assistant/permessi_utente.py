"""Permessi reali dell'utente corrente, per le domande «posso…?» all'assistente.

Senza questo contesto il modello tirava a indovinare («non hai accesso al modulo»).
Qui si legge, per il modulo nominato nella domanda:

- se l'utente può aprire il modulo (stessa decisione ACL v2 della rotta);
- le azioni del modulo con SÌ/NO: dai controlli in-view del modulo quando esistono
  (es. Registro Timbri) o dai permessi canonici ``PermissionDefinition`` del modulo.

Sono i permessi dell'utente stesso: nessun dato di altri. Solo lettura, fail-safe:
un controllo che fallisce vale NO.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

MAX_AZIONI = 12
MAX_MODULI = 2


@dataclass(frozen=True)
class ModuloPermessi:
    slug: str
    nome: str
    path: str
    # Inizi di parola con cui gli utenti nominano il modulo (testo già minuscolo).
    parole: tuple[str, ...]
    # Modulo dei permessi canonici (PermissionDefinition.module), se ne ha.
    acl_module: str = ""
    # Controlli in-view del modulo: [(etichetta, funzione(request) -> bool)].
    azioni: Callable[[], list[tuple[str, Callable]]] | None = None
    # Prefisso delle fonti del tool live che legge i dati del modulo, se esiste.
    tool_prefix: str = ""
    parole_re: re.Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        pattern = r"\b(?:" + "|".join(re.escape(p) for p in self.parole) + r")"
        object.__setattr__(self, "parole_re", re.compile(pattern))


def _azioni_timbri() -> list[tuple[str, Callable]]:
    from timbri import views

    return [
        ("Consultare il registro", views._can_view_timbri),
        ("Creare, modificare e archiviare record (pulsanti «Nuovo record», «Modifica», «Archivia»)", views._can_edit_timbri),
        ("Copiare un'immagine («Copia»)", views._can_copy_timbri),
        ("Scaricare il file PNG («Scarica»)", views._can_download_timbri),
        ("Impostazioni del modulo", views._can_manage_timbri_config),
    ]


MODULI: tuple[ModuloPermessi, ...] = (
    ModuloPermessi("timbri", "Registro Timbri (MOD.130-RTF)", "/timbri/",
                   ("timbro", "timbri", "registro timbri", "firma", "firme", "sigla", "sigle"),
                   azioni=_azioni_timbri),
    ModuloPermessi("tickets", "Ticket", "/tickets/", ("ticket",), acl_module="tickets", tool_prefix="tool:tickets"),
    ModuloPermessi("anomalie", "Gestione anomalie", "/gestione-anomalie", ("anomali", "seriale", "seriali"),
                   acl_module="anomalie", tool_prefix="tool:anomalie"),
    ModuloPermessi("tasks", "KICK-OFF / attività", "/tasks/", ("kick-off", "kickoff", "progett", "task"),
                   acl_module="tasks", tool_prefix="tool:tasks"),
    ModuloPermessi("dpi", "DPI", "/dpi/", ("dpi",), acl_module="dpi", tool_prefix="tool:dpi"),
    ModuloPermessi("assets", "Asset e manutenzione", "/assets/", ("asset", "manutenzion", "ordine di lavoro", "odl"),
                   tool_prefix="tool:assets"),
    ModuloPermessi("assenze", "Assenze", "/assenze/", ("ferie", "assenz"), tool_prefix="tool:assenze"),
    ModuloPermessi("anagrafica", "Anagrafica", "/anagrafica/",
                   ("anagrafic", "dipendent", "formazione", "corso", "corsi", "visita medica", "visite mediche"),
                   acl_module="anagrafica", tool_prefix="tool:anagrafica"),
    ModuloPermessi("sistema_gestione", "Audit interni e Sistema di gestione", "/sistema-gestione/",
                   ("audit", "sistema di gestione"), acl_module="sistema_gestione"),
    ModuloPermessi("registro_ofi", "Registro OFI / NC", "/ofi-registro/", ("ofi", "non conformit")),
    ModuloPermessi("gestione_specifiche", "Gestione specifiche", "/gestione-specifiche/", ("specific",),
                   acl_module="gestione_specifiche"),
    ModuloPermessi("glossario", "Glossario tecnico", "/glossario/", ("glossari",), acl_module="glossario_tecnico"),
    ModuloPermessi("schede_sicurezza", "Schede di sicurezza", "/schede-sicurezza/",
                   ("scheda di sicurezza", "schede di sicurezza", "sds"), acl_module="schede_sicurezza",
                   tool_prefix="tool:schede_sicurezza"),
    ModuloPermessi("report_conformita", "Report conformità", "/report-conformita/", ("conformit",),
                   acl_module="report_conformita"),
    ModuloPermessi("rilevazione_incidenti", "Rilevazione incidenti", "/rilevazione-incidenti/",
                   ("incident", "near miss", "infortun"), acl_module="rilevazione_incidenti",
                   tool_prefix="tool:sicurezza"),
    ModuloPermessi("diario_preposto", "Diario del preposto", "/diario-preposto/", ("diario", "preposto"),
                   acl_module="diario_preposto", tool_prefix="tool:sicurezza"),
    ModuloPermessi("rentri", "RENTRI / rifiuti", "/rentri/", ("rentri", "rifiut"), acl_module="rentri"),
    ModuloPermessi("suggestion_corner", "Suggestion Corner", "/suggestion-corner/", ("suggestion", "suggeriment"),
                   acl_module="suggestion_corner", tool_prefix="tool:suggestion"),
    ModuloPermessi("carichi", "Carichi macchina", "/carichi-macchina/", ("carichi macchina", "carico macchina"),
                   acl_module="gestione_carichi_macchina", tool_prefix="tool:carichi"),
    ModuloPermessi("checklist", "Checklist operativa", "/checklist-operativa/", ("checklist",),
                   acl_module="checklist_operativa"),
    ModuloPermessi("attrezzature", "Gestione attrezzature", "/attrezzature/", ("attrezzatur",),
                   acl_module="attrezzature"),
    ModuloPermessi("procedure", "Procedure", "/procedure-refresh/", ("procedur", "presa visione", "prese visione"),
                   tool_prefix="tool:procedure_refresh"),
    ModuloPermessi("notizie", "Notizie", "/notizie/", ("notizi", "comunicazion"), tool_prefix="tool:notizie"),
    ModuloPermessi("contatori", "Contatori stampanti", "/contatori/", ("contator", "toner"),
                   tool_prefix="tool:contatori"),
    ModuloPermessi("ai_assistant", "Assistente AI", "/assistente-ai/", ("assistente", "faq"),
                   acl_module="ai_assistant"),
)


def moduli_citati(testo: str, limite: int = MAX_MODULI) -> list[ModuloPermessi]:
    """Moduli nominati nel testo (minuscolo), nell'ordine del registro."""
    text = (testo or "").lower()
    return [m for m in MODULI if m.parole_re.search(text)][:limite]


# Domande sui propri permessi. «permessi» da solo è ambiguo (ferie e permessi):
# le domande sulle assenze sono escluse da ``vuole_permessi``.
_INTENT_RE = re.compile(
    r"\b(posso|potrei|riesco|ho (il |i )?permess\w*|ho accesso|ho l'accesso|sono abilitat\w*|"
    r"sono autorizzat\w*|che permessi|quali permessi|cosa posso fare|non vedo|non trovo|non compare|"
    r"non mi (fa|lascia|compare|fa vedere)|perch[eé] non)\b"
)
_ASSENZE_RE = re.compile(r"\b(ferie|residu\w*|rol|ore di permesso|giorni di permesso|ratei)\b")


def vuole_permessi(testo: str) -> bool:
    text = (testo or "").lower()
    return bool(_INTENT_RE.search(text)) and not _ASSENZE_RE.search(text)


def _legacy_user(request):
    legacy = getattr(request, "legacy_user", None)
    if legacy is not None:
        return legacy
    try:
        from core.legacy_utils import get_legacy_user

        return get_legacy_user(request.user)
    except Exception:
        return None


def accesso_modulo(request, modulo: ModuloPermessi) -> bool:
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return False
    try:
        from core.acl_v2 import resolve_acl_access
        from core.legacy_utils import legacy_auth_enabled
    except Exception:
        return False
    if getattr(user, "is_superuser", False) or not legacy_auth_enabled():
        return True
    try:
        decision = resolve_acl_access(
            path=modulo.path,
            legacy_user=_legacy_user(request),
            django_user=user,
            request=request,
            include_legacy_diagnostic=False,
        )
    except Exception:
        return False
    return bool(decision.get("allowed"))


def _token_set(testo: str) -> set[str]:
    return {t for t in re.findall(r"[a-zà-ù]{4,}", (testo or "").lower())}


def azioni_modulo(request, modulo: ModuloPermessi, testo: str = "") -> tuple[list[tuple[str, bool]], int]:
    """(azioni mostrate con esito, numero totale di azioni del modulo)."""
    if modulo.azioni is not None:
        risultato: list[tuple[str, bool]] = []
        try:
            controlli = modulo.azioni()
        except Exception:
            return [], 0
        for etichetta, controllo in controlli:
            try:
                ok = bool(controllo(request))
            except Exception:
                ok = False
            risultato.append((etichetta, ok))
        return risultato, len(risultato)
    if not modulo.acl_module:
        return [], 0
    try:
        from core.acl_v2 import evaluate_permission_code_access
        from core.models import PermissionDefinition

        definizioni = list(
            PermissionDefinition.objects.filter(module=modulo.acl_module, is_active=True)
            .order_by("code")
            .values_list("code", "label")
        )
    except Exception:
        return [], 0
    totale = len(definizioni)
    if totale > MAX_AZIONI:
        # Moduli grandi (anagrafica): solo i permessi che toccano le parole della domanda.
        parole = _token_set(testo)
        pertinenti = [d for d in definizioni if parole & _token_set(f"{d[0].replace('.', ' ')} {d[1]}")]
        definizioni = (pertinenti or definizioni)[:MAX_AZIONI]
    legacy_user = _legacy_user(request)
    risultato = []
    for code, label in definizioni:
        try:
            ok = bool(evaluate_permission_code_access(
                permission_code=code, legacy_user=legacy_user, django_user=request.user,
            ).get("allowed"))
        except Exception:
            ok = False
        risultato.append((label or code, ok))
    return risultato, totale


# Domande che chiedono DATI (non «come si fa»): servono a capire su quali moduli
# gli utenti cercano dati che l'assistente non sa leggere.
_DATI_RE = re.compile(
    r"\b(quanti|quante|quali|quale|elenco|lista|mostra\w*|dimmi|chi|riepilogo|ultim[aeio]|"
    r"apert[aeio]|in scadenza|scadut[aeio]|stato)\b"
)
_COME_RE = re.compile(r"\b(come|dove|in che modo|posso|procedura)\b")


def moduli_senza_dati(testo: str, fonti_live) -> list[str]:
    """Slug dei moduli su cui la domanda chiede dati ma nessun tool live li ha letti.

    Solo slug di modulo (metadati), mai il testo: va nell'audit ``ai_chat`` e alimenta
    la scheda «Suggerimenti» di Gestione AI per decidere quali tool costruire.
    """
    text = (testo or "").lower()
    if not _DATI_RE.search(text) or _COME_RE.search(text):
        return []
    fonti = [str(f) for f in (fonti_live or ())]
    mancanti: list[str] = []
    for modulo in moduli_citati(text, limite=3):
        servito = bool(modulo.tool_prefix) and any(f.startswith(modulo.tool_prefix) for f in fonti)
        if not servito:
            mancanti.append(modulo.slug)
    return mancanti
