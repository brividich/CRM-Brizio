"""Guide d'uso in-app dei moduli come conoscenza dell'assistente AI.

Le guide che gli utenti aprono dal pulsante «? Guida» sono la descrizione più
fedele di *come si fa* una cosa nel portale (etichette reali dei pulsanti, soglie,
permessi). Questo modulo le raccoglie in testo semplice, una sezione per capitolo,
così che il RAG le possa citare con la fonte ``guida:<slug>``.

Tre formati di partenza, tutti già presenti nel repo:

- strutture Python ``SEZIONI`` con blocchi ``("p"|"ul"|"nota"|"def", ...)``
  (timbri, anomalie, audit/OFI);
- template HTML delle pagine guida (assets, formazione, e-learning, persone e
  account, specifiche, glossario): si prende il blocco ``content`` e si tolgono
  tag e sintassi Django;
- Markdown della guida del Security Center.

Gate ACL: una guida entra nella risposta solo se l'utente può aprire la pagina
della guida (stessa decisione ACL v2 della rotta). Fail-closed: senza request
nessuna guida. Tutto fail-safe: una guida illeggibile viene saltata, mai
un'eccezione propagata alla chat.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

SOURCE_PREFIX = "guida:"


@dataclass(frozen=True)
class Guida:
    slug: str
    modulo: str
    # URL della guida: link mostrato all'utente e rotta su cui si decide l'ACL.
    url: Callable[[], str]
    testo: Callable[[], str]
    # File da cui dipende il testo (per invalidare la cache dell'indice).
    file: Callable[[], list[Path]] = lambda: []
    # Parole con cui gli utenti nominano il modulo: titolo dei chunk per il BM25 e
    # riconoscimento del modulo citato nella domanda (vedi ``guide_menzionate``).
    parole: str = ""


@dataclass(frozen=True)
class SezioneGuida:
    slug: str
    modulo: str
    url: str
    titolo: str
    testo: str
    parole: str = ""


# ── Conversioni ─────────────────────────────────────────────────────────────


def _blocchi_in_testo(blocchi) -> str:
    righe: list[str] = []
    for blocco in blocchi or []:
        try:
            tipo, valore = blocco
        except (TypeError, ValueError):
            continue
        if tipo == "p":
            righe.append(str(valore))
        elif tipo == "nota":
            righe.append(f"Attenzione: {valore}")
        elif tipo == "ul":
            righe.extend(f"- {voce}" for voce in valore or [])
        elif tipo == "passi":
            righe.extend(f"{i}. {voce}" for i, voce in enumerate(valore or [], 1))
        elif tipo == "def":
            for coppia in valore or []:
                try:
                    termine, spiegazione = coppia
                except (TypeError, ValueError):
                    continue
                righe.append(f"- {termine}: {spiegazione}")
        righe.append("")
    return "\n".join(righe).strip()


def sezioni_in_markdown(sezioni) -> str:
    parti: list[str] = []
    for sezione in sezioni or []:
        titolo = str(sezione.get("titolo") or "").strip()
        corpo = _blocchi_in_testo(sezione.get("blocchi"))
        if titolo and corpo:
            parti.append(f"## {titolo}\n\n{corpo}")
    return "\n\n".join(parti)


_BLOCK_CONTENT_RE = re.compile(r"{%\s*block\s+content\s*%}(.*?){%\s*endblock", re.S)
_DJ_COMMENT_RE = re.compile(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}|{#.*?#}", re.S)
_DJ_TAG_RE = re.compile(r"{%.*?%}", re.S)
_DJ_VAR_RE = re.compile(r"{{.*?}}", re.S)
# Varianti brevi per l'utente che guarda la pagina («Puoi …» / «non abilitato per te»):
# per la conoscenza condivisa non valgono, si tolgono entrambi i rami.
_DJ_IF_ELSE_SHORT_RE = re.compile(
    r"{%\s*if\b[^%]*%}(?:(?!{%\s*(?:if|endif)\b).){0,300}?{%\s*else\s*%}"
    r"(?:(?!{%\s*(?:if|endif)\b).){0,300}?{%\s*endif\s*%}",
    re.S,
)
_STYLE_SCRIPT_RE = re.compile(r"<(style|script)\b.*?</\1\s*>", re.S | re.I)
_HEADING_RE = re.compile(r"<h([1-4])\b[^>]*>(.*?)</h\1\s*>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def html_in_markdown(sorgente: str) -> str:
    """Testo leggibile da un template guida: headings in Markdown, elenchi a trattini.

    Le variabili di template (soglie lette da settings) non sono risolvibili senza
    request: vengono tolte, quindi il testo resta corretto ma senza quel numero.
    """
    match = _BLOCK_CONTENT_RE.search(sorgente)
    testo = match.group(1) if match else sorgente
    testo = _DJ_COMMENT_RE.sub("", testo)
    testo = _STYLE_SCRIPT_RE.sub("", testo)
    testo = _DJ_IF_ELSE_SHORT_RE.sub("", testo)
    testo = _DJ_TAG_RE.sub("", testo)
    testo = _DJ_VAR_RE.sub("", testo)
    testo = _HEADING_RE.sub(lambda m: f"\n\n{'#' * max(2, int(m.group(1)))} {_TAG_RE.sub('', m.group(2)).strip()}\n\n", testo)
    testo = re.sub(r"<li\b[^>]*>", "\n- ", testo, flags=re.I)
    testo = re.sub(r"<(dt)\b[^>]*>", "\n- ", testo, flags=re.I)
    testo = re.sub(r"</t[hd]\s*>", " · ", testo, flags=re.I)
    testo = re.sub(r"</?(p|div|ul|ol|dl|dd|section|table|tr|br|nav|header)\b[^>]*>", "\n", testo, flags=re.I)
    testo = _TAG_RE.sub("", testo)
    testo = html.unescape(testo)
    righe = [re.sub(r"[ \t]+", " ", riga).strip() for riga in testo.splitlines()]
    righe = [re.sub(r"(\s*·\s*)+$", "", riga) for riga in righe if riga not in {"-", "←", "→"}]
    testo = "\n".join(righe)
    # Primo h1 = titolo della pagina: lo porta già il titolo del chunk.
    testo = re.sub(r"^\s*##\s+[^\n]*\n", "", testo.strip(), count=1)
    return re.sub(r"\n{3,}", "\n\n", testo).strip()


# ── Registro delle guide ────────────────────────────────────────────────────


def _reverse(name: str, query: str = "", **kwargs) -> Callable[[], str]:
    def _url() -> str:
        from django.urls import reverse

        return reverse(name, kwargs=kwargs or None) + query

    return _url


def _template_source(nome: str) -> str:
    from django.template.loader import get_template

    return get_template(nome).template.source


def _template_path(nome: str) -> list[Path]:
    from django.template.loader import get_template

    origin = getattr(get_template(nome).template, "origin", None)
    nome_file = getattr(origin, "name", "")
    return [Path(nome_file)] if nome_file else []


def _da_template(nome: str) -> tuple[Callable[[], str], Callable[[], list[Path]]]:
    return (lambda: html_in_markdown(_template_source(nome)), lambda: _template_path(nome))


def _testo_timbri() -> str:
    from timbri import guida

    return sezioni_in_markdown(guida.SEZIONI)


def _testo_kickoff() -> str:
    from tasks import guida

    return sezioni_in_markdown(guida.SEZIONI)


def _testo_anomalie() -> str:
    from anomalie import guida

    return sezioni_in_markdown(guida.SEZIONI)


def _testo_audit() -> str:
    from sistema_gestione import guida

    # I capitoli del Registro OFI sono indicizzati con la guida OFI: qui solo il resto,
    # così lo stesso testo non occupa due posti nel top-k.
    ofi_ids = {sezione.get("id") for sezione in guida.GUIDA_OFI["sezioni"]}
    return sezioni_in_markdown([s for s in guida.GUIDA_AUDIT["sezioni"] if s.get("id") not in ofi_ids])


def _testo_ofi() -> str:
    from sistema_gestione import guida

    return sezioni_in_markdown(guida.GUIDA_OFI["sezioni"])


def _testo_home() -> str:
    from dashboard import guida

    return sezioni_in_markdown(guida.SEZIONI)


def _testo_assistente() -> str:
    from ai_assistant import guida

    return sezioni_in_markdown(guida.sezioni())


def _file_modulo(modulo: str) -> Callable[[], list[Path]]:
    def _file() -> list[Path]:
        import importlib

        percorso = getattr(importlib.import_module(modulo), "__file__", "")
        return [Path(percorso)] if percorso else []

    return _file


# Documenti della guida SOC rivolti a chi usa il Security Center (esclusi quelli
# per sviluppatori e i dettagli degli add-on).
_SOC_DOCS = (
    "00_START_HERE.md",
    "02_ADMIN_GUIDE.md",
    "07_ALERT_LIFECYCLE.md",
    "08_CONFIGURATION_GUIDE.md",
    "09_TROUBLESHOOTING.md",
    "11_OPERATIONS_RUNBOOK.md",
    "12_AUTOMATISMI_E_VULNERABILITA.md",
    "13_LAVORO_QUOTIDIANO.md",
    "14_INCIDENTI_E_REPORT.md",
    "15_BACKUP_VPN_KPI_ASSET.md",
    "16_IMPOSTAZIONI_E_AI.md",
    "17_MODULI_DIAGNOSTICA_DOCUMENTAZIONE.md",
)


def _guida_soc(nome_file: str) -> Guida:
    def _percorso() -> Path:
        from security.docs_render import GUIDE_DIR

        return GUIDE_DIR / nome_file

    def _testo() -> str:
        return _percorso().read_text(encoding="utf-8", errors="replace")

    def _url() -> str:
        from django.urls import reverse

        from security.docs_render import slug_for

        return reverse("security:doc_detail", kwargs={"slug": slug_for(nome_file)})

    slug = "soc-" + nome_file[:-3].lower().replace("_", "-")
    return Guida(slug=slug, modulo="Security Center (SOC)", url=_url, testo=_testo, file=lambda: [_percorso()],
                 parole="soc sicurezza informatica alert allarme allarmi vulnerabilita incidente incidenti")


def _registro() -> list[Guida]:
    guide = [
        Guida("timbri", "Registro Timbri (MOD.130-RTF)", _reverse("timbri:index", "?guida=1"), _testo_timbri,
              _file_modulo("timbri.guida"), parole="timbro timbri firma firme sigla sigle"),
        Guida("kickoff", "KICK-OFF (commesse, incontri, azioni)", _reverse("tasks:guida"), _testo_kickoff,
              _file_modulo("tasks.guida"), parole="kickoff incontro incontri convocazione minuta azione azioni attivita commessa"),
        Guida("anomalie", "Gestione anomalie", lambda: "/gestione-anomalie?guida=1", _testo_anomalie,
              _file_modulo("anomalie.guida"), parole="anomalia anomalie seriale seriali capocommessa"),
        Guida("audit", "Audit interni (MT CN 12)", _reverse("sistema_gestione:audit_guida"), _testo_audit,
              _file_modulo("sistema_gestione.guida"), parole="audit auditor ispettiva ispettive"),
        Guida("registro-ofi", "Registro OFI / NC (MOD.174)", _reverse("registro_ofi:guida"), _testo_ofi,
              _file_modulo("sistema_gestione.guida"), parole="ofi conformita correttiva correttive miglioramento"),
        Guida("home", "Home del portale", _reverse("home_portale:guida"), _testo_home,
              _file_modulo("dashboard.guida"), parole="home stanza stanze self-help scaffale rspp rls preposto"),
    ]
    for slug, modulo, url_name, template, parole in (
        ("assets", "Asset e manutenzione", "assets:guida", "assets/pages/guida.html",
         "asset qr etichetta etichette stampante stampanti mfc"),
        ("formazione", "Formazione", "anagrafica:formazione_guida", "anagrafica/pages/formazione_guida.html",
         "formazione corso corsi edizione edizioni attestato attestati"),
        ("formazione-online", "Formazione online (e-learning)", "anagrafica:formazione_online_guida",
         "anagrafica/pages/formazione_online_guida.html", "elearning online quiz"),
        ("persone-account", "Persone e account", "anagrafica:guida_persone_account",
         "anagrafica/pages/guida_persone_account.html", "dipendente dipendenti account"),
        ("specifiche", "Gestione specifiche", "gestione_specifiche:guida", "gestione_specifiche/guida.html",
         "specifica specifiche"),
        ("glossario", "Glossario tecnico", "glossario_tecnico:guida", "glossario_tecnico/pages/guida.html",
         "glossario"),
    ):
        testo, file = _da_template(template)
        guide.append(Guida(slug, modulo, _reverse(url_name), testo, file, parole=parole))
    # Guide amministrative: il gate ACL sulla loro pagina le riserva a chi gestisce i permessi.
    for slug, modulo, url_name, query, template, parole in (
        ("ruoli-permessi", "Ruoli e permessi", "admin_portale:ruoli_portale", "?tab=guida",
         "admin_portale/components/ruoli_portale_guida.html", "ruolo ruoli permesso permessi matrice"),
        ("accessi", "Accessi (permessi di pagina)", "admin_portale:accessi", "?guida=1",
         "admin_portale/components/accessi_guida.html", "accessi accesso gruppo gruppi acl permesso permessi"),
    ):
        testo, file = _da_template(template)
        guide.append(Guida(slug, modulo, _reverse(url_name, query), testo, file, parole=parole))
    guide.append(Guida("assistente-ai", "Assistente AI", _reverse("ai_assistant:guida"), _testo_assistente,
                       _file_modulo("ai_assistant.guida"), parole="assistente chatbot chat conversazione conversazioni"))
    guide.extend(_guida_soc(nome) for nome in _SOC_DOCS)
    guide.extend(_guide_centro())
    return guide


def _guide_centro() -> list[Guida]:
    """Centro guide (``core/guide_moduli``): solo la parte «Come si usa».

    Le parti per amministratori restano fuori dall'indice: l'assistente risponde a
    tutti, e la configurazione non deve finire nelle risposte a chi usa i moduli.
    Restano fuori anche i moduli con una guida di dettaglio già registrata qui sopra
    (timbri, anomalie, asset…): la sintesi del Centro guide le ripeterebbe in breve e
    toglierebbe posto nel top-k al testo completo.
    """
    from core import guide_moduli

    elenco = []
    for guida in guide_moduli.tutte():
        if guida["solo_admin"] or guida["dettaglio"]:
            continue

        def _testo(guida=guida) -> str:
            return sezioni_in_markdown(guide_moduli.capitoli_uso(guida))

        elenco.append(Guida(
            "centro-" + guida["slug"].replace("_", "-"),
            guida["titolo"],
            _reverse("guida_modulo", slug=guida["slug"]),
            _testo,
            _file_modulo(f"core.guide_moduli.contenuti.{guida['slug']}"),
            parole=guida.get("parole", ""),
        ))
    return elenco


def guide() -> list[Guida]:
    return _registro()


# ── Testo indicizzabile ─────────────────────────────────────────────────────


def _sezioni_markdown(testo: str) -> list[tuple[str, str]]:
    """(titolo, corpo) per ogni heading ``#``/``##``/``###`` del testo."""
    sezioni: list[tuple[str, list[str]]] = []
    titolo = ""
    righe: list[str] = []
    for riga in testo.splitlines():
        heading = re.match(r"^\s{0,3}#{1,3}\s+(.+?)\s*$", riga)
        if heading:
            if righe and "\n".join(righe).strip():
                sezioni.append((titolo, righe))
            titolo = heading.group(1).strip()
            righe = []
        else:
            righe.append(riga)
    if righe and "\n".join(righe).strip():
        sezioni.append((titolo, righe))
    return [(t, "\n".join(r).strip()) for t, r in sezioni]


@lru_cache(maxsize=1)
def _sezioni_cache(_firma: tuple) -> tuple[SezioneGuida, ...]:
    risultato: list[SezioneGuida] = []
    for guida in guide():
        try:
            testo = guida.testo()
            url = guida.url()
        except Exception as exc:  # guida assente/illeggibile: si salta
            logger.debug("ai_assistant: guida %s non indicizzata: %s", guida.slug, exc)
            continue
        for titolo, corpo in _sezioni_markdown(testo or ""):
            # Indici e sommari («In questa guida»): solo righe corte, nessuna frase.
            if len(corpo) < 40 or not any(len(riga) >= 50 for riga in corpo.splitlines()):
                continue
            risultato.append(SezioneGuida(guida.slug, guida.modulo, url, titolo or guida.modulo, corpo, guida.parole))
    return tuple(risultato)


def firma() -> tuple:
    """Firma economica per invalidare l'indice RAG quando cambia un file di guida."""
    voci: list[tuple] = []
    for guida in guide():
        try:
            for path in guida.file():
                stat = path.stat()
                voci.append((guida.slug, str(path), stat.st_mtime_ns, stat.st_size))
        except Exception:
            voci.append((guida.slug, "", 0, 0))
    return tuple(voci)


def sezioni() -> tuple[SezioneGuida, ...]:
    try:
        return _sezioni_cache(firma())
    except Exception as exc:
        logger.debug("ai_assistant: indicizzazione guide fallita: %s", exc)
        return ()


def guide_menzionate(tokens, tokenize: Callable[[str], list[str]] = str.split) -> frozenset[str]:
    """Slug delle guide il cui modulo è nominato fra i token della domanda.

    ``tokenize`` è lo stesso tokenizzatore del RAG (stemming compreso), così parole
    del modulo e domanda si confrontano nella stessa forma.
    """
    presenti = set(tokens or ())
    if not presenti:
        return frozenset()
    trovate: set[str] = set()
    for guida in guide():
        parole = set(tokenize(guida.parole))
        if parole & presenti:
            trovate.add(guida.slug)
    return frozenset(trovate)


def slug_da_source(source: str) -> str | None:
    if not source.startswith(SOURCE_PREFIX):
        return None
    return source[len(SOURCE_PREFIX):].split("#", 1)[0] or None


# ── Gate ACL ────────────────────────────────────────────────────────────────


def guide_consentite(request) -> frozenset[str]:
    """Slug delle guide che l'utente potrebbe aprire nel portale (ACL v2 della rotta).

    Fail-closed: request assente → nessuna guida. Superuser o legacy-auth spenta
    (dev/test, il middleware non applica gate) → tutte.
    """
    if request is None:
        return frozenset()
    elenco = guide()
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    try:
        from core.acl_v2 import resolve_acl_access
        from core.legacy_utils import get_legacy_user, legacy_auth_enabled
    except Exception:
        return frozenset()
    if getattr(user, "is_superuser", False) or not legacy_auth_enabled():
        return frozenset(g.slug for g in elenco)

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(user)
    consentite: set[str] = set()
    for guida in elenco:
        try:
            path = guida.url().split("?", 1)[0]
            decision = resolve_acl_access(
                path=path,
                legacy_user=legacy_user,
                django_user=user,
                request=request,
                include_legacy_diagnostic=False,
            )
        except Exception:
            continue
        if decision.get("allowed"):
            consentite.add(guida.slug)
    return frozenset(consentite)
