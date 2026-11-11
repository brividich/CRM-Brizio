"""CN-SGI: la libreria delle procedure della share SGI.

Funzioni di sola lettura usate dalle pagine della libreria, dall'apertura dei
documenti, dalla Bacheca e dall'assistente AI:

- **scaffali e sezioni**: uno scaffale per cartella di primo livello della share
  (``ProcedureDocument.category``), una sezione per sottocartella
  (``ProcedureDocument.sezione``). Nome e colore di default si ricavano dal nome
  della cartella; chi gestisce CN-SGI li cambia da «Scaffali».
- **chi vede cosa** (:class:`Visibilita`): regole per scaffale, sezione o
  documento; vince la più specifica. Senza regole il documento è di tutti. Chi
  gestisce CN-SGI, gli amministratori e i ruoli «vede tutto» vedono tutto; i
  documenti sensibili (``escludi_dal_rag`` o deny-list) solo chi gestisce.
- **ricerca** (:func:`cerca`): codice, titolo e testo estratto dei PDF in vigore,
  con estratto, sezione § e pagina.

La share non viene mai scritta: qui si legge soltanto il database.
"""
from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path, PureWindowsPath

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone
from django.utils.text import slugify

# Colori di default per le norme note; gli altri scaffali prendono un colore della tavolozza.
COLORI_NORME = {
    "9100": "#1f4f86",
    "9001": "#1f4f86",
    "27001": "#0f766e",
    "45001": "#b45309",
    "14001": "#3f7d3a",
    "125": "#8b3a62",
}
TAVOLOZZA = ["#335c67", "#475569", "#7a4f9a", "#a0522d", "#2f6f8f", "#5b6b2f"]
NORME_DEFAULT = {
    "9100": "EN 9100 · ISO 9001",
    "27001": "ISO/IEC 27001",
    "45001": "ISO 45001",
    "14001": "ISO 14001",
    "125": "UNI/PdR 125",
}
SCAFFALE_SENZA_CARTELLA = "Altri documenti"
SEZIONE_SENZA_CARTELLA = "Documenti"
GIORNI_NUOVE_REVISIONI = 30
GIORNI_PIU_CONSULTATI = 90


# ---------------------------------------------------------------------------
# Scaffali e sezioni
# ---------------------------------------------------------------------------


def _pulisci(nome: str) -> str:
    return re.sub(r"\s+", " ", (nome or "").replace("_", " ")).strip()


def identita_da_cartella(cartella: str) -> dict:
    """Sigla, nome, norma e colore di default di uno scaffale dal nome della cartella.

    «9100_Qualità» → sigla 9100, nome Qualità; «_PART 145» → PART 145;
    «_Piani Qualitá» → Piani Qualità (la «á» della cartella diventa «à»).
    """
    raw = (cartella or "").strip()
    if not raw:
        return {"sigla": "", "nome": SCAFFALE_SENZA_CARTELLA, "norma": "", "colore": "#475569"}
    m = re.match(r"^(\d{2,5})[_\s-]+(.+)$", raw)
    if m:
        sigla, nome = m.group(1), _pulisci(m.group(2))
    else:
        nome = _pulisci(raw.lstrip("_ "))
        sigla = ""
    nome = nome.replace("Qualitá", "Qualità")
    m_num = re.match(r"^([A-Za-z]+)\s+(\d{2,5})$", nome)
    if not sigla and m_num:
        sigla = m_num.group(2)
    if not sigla:
        parole = [p for p in nome.split() if p[:1].isalnum()]
        numeri = [p for p in parole if p.isdigit()]
        sigla = " ".join(parole) if len(nome) <= 9 else ("".join(p[0] for p in parole[:3]).upper() + (f" {numeri[0]}" if numeri else ""))
    colore = COLORI_NORME.get(sigla)
    if not colore:
        colore = TAVOLOZZA[sum(map(ord, raw)) % len(TAVOLOZZA)]
    norma = NORME_DEFAULT.get(sigla, "")
    if not norma and "part" in nome.lower():
        norma = "EASA Part 145"
    elif not norma and "piani" in nome.lower():
        norma = "Requisiti dei clienti"
    return {"sigla": sigla[:20], "nome": nome[:120] or raw[:120], "norma": norma, "colore": colore}


ORDINE_NORME = {"9100": 10, "9001": 10, "27001": 20, "45001": 30, "14001": 35, "125": 40, "145": 50}


def ordine_default(cartella: str) -> int:
    """Posizione di default dello scaffale: prima le certificazioni principali, poi il resto."""
    ident = identita_da_cartella(cartella)
    if ident["sigla"] in ORDINE_NORME:
        return ORDINE_NORME[ident["sigla"]]
    return 60 if "piani" in ident["nome"].lower() else 90


def etichetta_sezione(sezione: str) -> str:
    """«2_MT» → «MT», «_Modelli» → «Modelli», vuota → «Documenti»."""
    s = re.sub(r"^[\d]+[_\s.-]+", "", (sezione or "").strip())
    s = _pulisci(s.lstrip("_ "))
    return s or SEZIONE_SENZA_CARTELLA


def sezione_da_percorso(percorso: str, radice: str) -> str:
    """Sottocartella sotto lo scaffale (secondo livello della share), «» se il file sta nello scaffale.

    Lavora sulle stringhe (percorsi UNC di Windows anche su altri sistemi), senza
    toccare il file system.
    """
    if not percorso or not radice:
        return ""
    try:
        p = PureWindowsPath(percorso)
        r = PureWindowsPath(radice)
        rel = p.relative_to(r) if str(p).lower().startswith(str(r).lower()) else None
    except ValueError:
        rel = None
    if rel is None:
        low_p, low_r = percorso.replace("/", "\\").lower(), radice.replace("/", "\\").rstrip("\\").lower()
        if not low_p.startswith(low_r + "\\"):
            return ""
        parti = percorso.replace("/", "\\")[len(low_r) + 1:].split("\\")
    else:
        parti = list(rel.parts)
    # parti = [scaffale, sezione, ..., file]
    return parti[1][:255] if len(parti) > 2 else ""


def slug_scaffale(cartella: str) -> str:
    return slugify(cartella or "") or "altri"


@dataclass
class Scaffale:
    cartella: str
    slug: str
    nome: str
    sigla: str
    norma: str
    colore: str
    ordine: int = 100
    certificazione: object = None
    totale: int = 0
    nuovi: int = 0
    sezioni: list = field(default_factory=list)  # [(sezione_raw, etichetta, n)]
    icona: str = ""
    logo_url: str = ""


def scaffali_configurati() -> dict[str, object]:
    from procedure_refresh.models import SgiScaffale

    try:
        return {s.cartella: s for s in SgiScaffale.objects.select_related("certificazione")}
    except Exception:
        return {}


def scaffale_da(cartella: str, config: dict) -> Scaffale:
    row = config.get(cartella)
    base = identita_da_cartella(cartella)
    if row is None:
        return Scaffale(cartella=cartella, slug=slug_scaffale(cartella), ordine=ordine_default(cartella), **base)
    return Scaffale(
        cartella=cartella,
        slug=slug_scaffale(cartella),
        nome=row.nome or base["nome"],
        sigla=row.sigla or base["sigla"],
        norma=row.norma,
        colore=row.colore or base["colore"],
        ordine=row.ordine,
        certificazione=row.certificazione if getattr(row, "certificazione_id", None) else None,
        icona=getattr(row, "icona", "") or "",
        logo_url=_logo_url(row),
    )


def _logo_url(row) -> str:
    if not getattr(row, "logo", None):
        return ""
    from django.urls import reverse

    versione = int(row.aggiornato_il.timestamp()) if getattr(row, "aggiornato_il", None) else 0
    return f"{reverse('procedure_refresh:libreria_scaffale_logo', args=[row.pk])}?v={versione}"


def assicura_scaffali() -> int:
    """Crea la riga ``SgiScaffale`` per le cartelle che non ce l'hanno. Ritorna quante ne crea."""
    from procedure_refresh.models import ProcedureDocument, SgiScaffale

    esistenti = set(SgiScaffale.objects.values_list("cartella", flat=True))
    cartelle = set(
        ProcedureDocument.objects.filter(is_active=True).exclude(category="").values_list("category", flat=True)
    )
    nuove = sorted(c for c in cartelle if c and c not in esistenti)
    for i, cartella in enumerate(nuove):
        base = identita_da_cartella(cartella)
        try:
            with transaction.atomic():
                SgiScaffale.objects.create(cartella=cartella[:100], ordine=ordine_default(cartella), **base)
        except IntegrityError:
            pass
    return len(nuove)


def aggiorna_sezioni() -> int:
    """Riallinea ``ProcedureDocument.sezione`` dal percorso della revisione corrente. Ritorna i cambi."""
    from procedure_refresh.models import ProcedureRevision

    radice = str(getattr(settings, "PROCEDURE_REFRESH_SGI_SHARE_ROOT", "") or "").strip()
    if not radice:
        return 0
    cambi = 0
    revs = ProcedureRevision.objects.filter(is_current=True).exclude(source_path="").select_related("document")
    for rev in revs:
        sez = sezione_da_percorso(rev.source_path, radice)
        doc = rev.document
        if doc.sezione != sez:
            doc.sezione = sez
            doc.save(update_fields=["sezione", "updated_at"])
            cambi += 1
    return cambi


# ---------------------------------------------------------------------------
# Chi vede cosa
# ---------------------------------------------------------------------------


class Visibilita:
    """Decide quali documenti vede chi fa la richiesta. Una istanza per richiesta."""

    def __init__(self, request=None, *, gestore: bool | None = None, gruppi: set[int] | None = None, vede_tutto: bool | None = None):
        from procedure_refresh.models import SgiVisibilita

        self.request = request
        if gestore is None:
            from procedure_refresh.views import _can_manage

            gestore = bool(request is not None and _can_manage(request))
        self.gestore = gestore
        if gruppi is None or vede_tutto is None:
            g, vt = self._gruppi(request)
            gruppi = g if gruppi is None else gruppi
            vede_tutto = vt if vede_tutto is None else vede_tutto
        self.gruppi = set(gruppi or ())
        self.vede_tutto = bool(vede_tutto) or self.gestore
        self.per_documento: dict[int, object] = {}
        self.per_sezione: dict[tuple[str, str], object] = {}
        self.per_scaffale: dict[str, object] = {}
        try:
            for r in SgiVisibilita.objects.prefetch_related("ruoli"):
                r.ruoli_ids = {g.pk for g in r.ruoli.all()}
                if r.documento_id:
                    self.per_documento[r.documento_id] = r
                elif r.sezione:
                    self.per_sezione[(r.scaffale, r.sezione)] = r
                else:
                    self.per_scaffale[r.scaffale] = r
        except Exception:
            pass

    @staticmethod
    def _gruppi(request) -> tuple[set[int], bool]:
        if request is None or not getattr(request, "user", None) or not request.user.is_authenticated:
            return set(), False
        if request.user.is_superuser:
            return set(), True
        try:
            from core.acl_resolver import user_group_ids
            from core.legacy_utils import get_legacy_user, is_legacy_admin
            from core.models import AccessGroup

            legacy = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
            if legacy is not None and is_legacy_admin(legacy):
                return set(), True
            ids = set(user_group_ids(getattr(legacy, "id", None))) if legacy is not None else set()
            vede_tutto = bool(ids) and AccessGroup.objects.filter(pk__in=ids).filter(
                Q(amministratore=True) | Q(vede_tutto=True)
            ).exists()
            return ids, vede_tutto
        except Exception:
            return set(), False

    def regola(self, doc):
        """La regola che decide per il documento (la più specifica), o None."""
        return (
            self.per_documento.get(doc.pk)
            or self.per_sezione.get((doc.category or "", doc.sezione or ""))
            or self.per_scaffale.get(doc.category or "")
        )

    def puo_vedere(self, doc) -> bool:
        from procedure_refresh.bacheca import documento_e_sensibile

        if not doc.is_active:
            return False
        if self.gestore:
            return True
        if documento_e_sensibile(doc):
            return False
        if self.vede_tutto:
            return True
        regola = self.regola(doc)
        if regola is None:
            return True
        if regola.chi == "nessuno":
            return False
        return bool(self.gruppi & regola.ruoli_ids)

    def filtra(self, docs):
        return [d for d in docs if self.puo_vedere(d)]


def codici_riservati() -> set[str]:
    """Codici dei documenti con una regola di visibilità (non aperti a tutti).

    Usato dall'assistente AI per non citare a chiunque documenti riservati a qualche ruolo.
    """
    from procedure_refresh.models import ProcedureDocument

    vis = visibilita_di_tutti()
    if not (vis.per_documento or vis.per_sezione or vis.per_scaffale):
        return set()
    docs = ProcedureDocument.objects.filter(is_active=True).only("id", "code", "category", "sezione", "is_active")
    return {d.code for d in docs if vis.regola(d) is not None}


def visibilita_di_tutti() -> Visibilita:
    """Il punto di vista di un dipendente senza ruoli: vede solo ciò che è aperto a tutti."""
    return Visibilita(None, gestore=False, gruppi=set(), vede_tutto=False)


# ---------------------------------------------------------------------------
# Catalogo visibile
# ---------------------------------------------------------------------------


def documenti_in_vigore():
    """Documenti attivi con revisione corrente, con la revisione già caricata in ``doc.rev``."""
    from procedure_refresh.models import ProcedureDocument

    docs = list(
        ProcedureDocument.objects.filter(is_active=True)
        .prefetch_related("revisions")
        .order_by("category", "sezione", "code")
    )
    out = []
    for d in docs:
        rev = next((r for r in d.revisions.all() if r.is_current), None)
        if rev is None:
            continue
        d.rev = rev
        out.append(d)
    return out


def codici_nuove_revisioni(giorni: int = GIORNI_NUOVE_REVISIONI) -> dict[str, object]:
    """Codice → data dell'ultima novità (nuovo documento o nuova revisione) negli ultimi N giorni."""
    from procedure_refresh.models import SgiSyncAction, SgiSyncLog

    da = timezone.now() - timedelta(days=giorni)
    out: dict[str, object] = {}
    try:
        righe = SgiSyncLog.objects.filter(
            created_at__gte=da, azione__in=[SgiSyncAction.NUOVO_DOC, SgiSyncAction.NUOVA_REVISIONE]
        ).values_list("document_code", "created_at")
        for code, quando in righe:
            if code not in out or quando > out[code]:
                out[code] = quando
    except Exception:
        pass
    return out


def aperture_recenti(giorni: int = GIORNI_PIU_CONSULTATI) -> dict[int, int]:
    from procedure_refresh.models import SgiAperturaGiorno

    da = timezone.localdate() - timedelta(days=giorni)
    try:
        return dict(
            SgiAperturaGiorno.objects.filter(giorno__gte=da)
            .values_list("documento_id")
            .annotate(n=Sum("conteggio"))
            .values_list("documento_id", "n")
        )
    except Exception:
        return {}


def conta_apertura(doc) -> None:
    """Più uno alle aperture di oggi del documento (fail-safe)."""
    from procedure_refresh.models import SgiAperturaGiorno

    oggi = timezone.localdate()
    try:
        n = SgiAperturaGiorno.objects.filter(documento=doc, giorno=oggi).update(conteggio=F("conteggio") + 1)
        if not n:
            try:
                with transaction.atomic():
                    SgiAperturaGiorno.objects.create(documento=doc, giorno=oggi, conteggio=1)
            except IntegrityError:
                SgiAperturaGiorno.objects.filter(documento=doc, giorno=oggi).update(conteggio=F("conteggio") + 1)
    except Exception:
        pass


def letture_da_fare(user) -> dict[int, object]:
    """Documento → assegnazione ancora da confermare dell'utente (campagne pubblicate)."""
    from procedure_refresh.models import AssignmentStatus, CampaignStatus, ProcedureAssignment

    if not getattr(user, "is_authenticated", False):
        return {}
    out: dict[int, object] = {}
    try:
        qs = (
            ProcedureAssignment.objects.filter(
                user=user,
                status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED, AssignmentStatus.OVERDUE],
                campaign__status=CampaignStatus.PUBLISHED,
            )
            .select_related("revision", "campaign")
            .order_by("due_date")
        )
        for a in qs:
            out.setdefault(a.revision.document_id, a)
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# Ricerca
# ---------------------------------------------------------------------------

_SEZIONE_RE = re.compile(r"^[ \t]*(?:#+[ \t]*)?((?:§[ \t]*)?\d+(?:\.\d+){0,3})[.)]?[ \t]+[A-ZÀ-Ýa-zà-ÿ]", re.MULTILINE)
MAX_RISULTATI = 60
MAX_ESTRATTI = 2


def _piega(testo: str) -> str:
    """Minuscolo senza accenti, stessa lunghezza del testo (per trovare le posizioni)."""
    out = []
    for ch in testo or "":
        base = unicodedata.normalize("NFD", ch)[0]
        out.append(base.lower() if len(base.lower()) == 1 else ch.lower())
    return "".join(out)


def _pagina(offsets: list, pos: int, n_pagine: int | None, n_car: int) -> int | None:
    if offsets:
        return max(1, bisect.bisect_right(offsets, pos))
    if n_pagine and n_car:
        return min(n_pagine, max(1, int(pos / max(n_car, 1) * n_pagine) + 1))
    return None


def _sezione(testo: str, pos: int) -> str:
    ultima = ""
    for m in _SEZIONE_RE.finditer(testo, 0, pos + 1):
        if m.start() > pos:
            break
        ultima = m.group(1).replace(" ", "")
    if ultima and not ultima.startswith("§"):
        ultima = "§" + ultima
    return ultima


def _estratto(testo: str, pos: int, lunghezza: int, raggio: int = 110) -> tuple[str, str, str]:
    inizio = max(0, pos - raggio)
    fine = min(len(testo), pos + lunghezza + raggio)
    prima = testo[inizio:pos]
    if inizio > 0 and " " in prima:
        prima = "…" + prima[prima.index(" ") + 1:]
    dopo = testo[pos + lunghezza:fine]
    if fine < len(testo) and " " in dopo:
        dopo = dopo[: dopo.rindex(" ")] + "…"
    pulisci = lambda s: re.sub(r"\s*\|\s*", " · ", re.sub(r"\s+", " ", s))  # noqa: E731
    return pulisci(prima), pulisci(testo[pos:pos + lunghezza]), pulisci(dopo)


@dataclass
class Risultato:
    doc: object
    punteggio: int
    nel_titolo: bool
    estratti: list = field(default_factory=list)  # dict(prima, trovato, dopo, sezione, pagina)
    occorrenze: int = 0


class Risultati(list):
    """Elenco dei risultati con due note per la pagina: corrispondenze parziali e parole corrette."""

    approssimati: bool = False
    corrette: list = []  # [(parola scritta, parola trovata)]


# Parole che non aiutano a trovare un documento: si ignorano (se la ricerca è fatta solo
# di queste, si tengono).
PAROLE_VUOTE = frozenset(
    "a ad al alla alle allo agli ai all con col da dal dalla dalle dallo dagli dai dei del della delle "
    "dello degli di e ed i il in la le lo gli nel nella nelle nello negli nei per su sul sulla sulle "
    "tra fra un una uno o od che come cosa chi quando dove non piu".split()
)
RAGGIO_VICINANZA = 160


@dataclass
class _Gruppo:
    parola: str
    radici: tuple
    simile: str = ""  # parola del corpus usata al posto di una scritta male


def _radice(parola: str) -> str:
    """Radice per trovare singolare, plurale e forme vicine: «procedure» → «procedu», «06» → «6»."""
    if parola.isdigit():
        return parola.lstrip("0") or "0"
    if len(parola) <= 4:
        return parola
    return parola[: max(4, len(parola) - 2)]


def _parole_query(q: str) -> list[str]:
    pezzi = re.findall(r"[a-z]+|[0-9]+", _piega(q))
    utili = [p for p in pezzi if p not in PAROLE_VUOTE]
    visti, out = set(), []
    for p in utili or pezzi:
        if p not in visti:
            visti.add(p)
            out.append(p)
    return out[:8]


def _regex(radici) -> re.Pattern:
    alternative = []
    for r in radici:
        if r.isdigit():
            alternative.append(r"(?<![0-9])0*" + r + r"(?![0-9])")
        else:
            alternative.append(r"(?<![a-z0-9])" + re.escape(r))
    return re.compile("|".join(alternative))


_VOCABOLARIO: dict = {"chiave": None, "parole": []}


def _vocabolario(testi: dict, docs: list) -> list[str]:
    """Parole del corpus (titoli e testi in vigore) per correggere quelle scritte male."""
    chiave = (len(testi), sum(len(t.piegato) for t in testi.values()), len(docs))
    if _VOCABOLARIO["chiave"] != chiave:
        parole = set()
        for t in testi.values():
            parole.update(re.findall(r"[a-z]{5,}", t.piegato))
        for d in docs:
            parole.update(re.findall(r"[a-z]{5,}", _piega(f"{d.code} {d.title}")))
        _VOCABOLARIO.update(chiave=chiave, parole=sorted(parole))
    return _VOCABOLARIO["parole"]


def _fine_parola(testo: str, pos: int) -> int:
    fine = pos
    while fine < len(testo) and (testo[fine].isalnum()):
        fine += 1
    return max(fine, pos + 1)


def cerca(q: str, docs: list, *, campo: str = "tutto") -> Risultati:
    """Ricerca flessibile nei documenti dati (già filtrati per visibilità).

    - le parole valgono in qualunque ordine, anche lontane fra loro; le parole vuote
      («di», «della», «per»…) non contano;
    - ogni parola si cerca per radice: «procedura» trova anche «procedure», «conformita»
      trova «conformità» (niente maiuscole né accenti);
    - i numeri valgono con o senza zeri: «MT 6» trova «MT CN 06», «mod93» trova «MOD.093»;
    - una parola che non c'è da nessuna parte si sostituisce con la più simile del corpus
      («confromità» → «conformità»);
    - se nessun documento ha tutte le parole, si mostrano quelli a cui ne manca una.

    ``campo``: «tutto», «titolo» (codice e titolo) o «testo».
    """
    import difflib

    risultati = Risultati()
    risultati.corrette = []
    q = re.sub(r"\s+", " ", (q or "").strip())
    parole = _parole_query(q)
    if len(q) < 2 or not parole:
        return risultati
    frase = _piega(q)
    gruppi = [_Gruppo(parola=p, radici=(_radice(p),)) for p in parole]

    usa_titolo = campo in ("tutto", "titolo")
    usa_testo = campo in ("tutto", "testo")
    per_rev = {d.rev.pk: d for d in docs}
    testi = _testi_piegati(list(per_rev)) if (usa_testo and per_rev) else {}
    intestazioni = {d.pk: _piega(f"{d.code} {d.title}") for d in docs}
    testo_di = {per_rev[r].pk: t for r, t in testi.items()}

    def trova(g):
        rx = _regex(g.radici)
        esiti = {}
        for d in docs:
            in_titolo = bool(usa_titolo and rx.search(intestazioni[d.pk]))
            pos = []
            t = testo_di.get(d.pk)
            if t is not None:
                for m in rx.finditer(t.piegato):
                    pos.append(m.start())
                    if len(pos) >= 60:
                        break
            if in_titolo or pos:
                esiti[d.pk] = (in_titolo, pos)
        return esiti

    esiti = [trova(g) for g in gruppi]
    for i, g in enumerate(gruppi):
        if esiti[i] or g.parola.isdigit() or len(g.parola) < 4:
            continue
        simili = difflib.get_close_matches(g.parola, _vocabolario(testi, docs), n=3, cutoff=0.78)
        if simili:
            g.radici = tuple(dict.fromkeys(_radice(s) for s in simili))
            g.simile = simili[0]
            esiti[i] = trova(g)
            risultati.corrette.append((g.parola, simili[0]))

    n = len(gruppi)
    trovati = {}
    for d in docs:
        presi = [i for i in range(n) if d.pk in esiti[i]]
        if presi:
            trovati[d.pk] = presi
    soglia = n
    if not any(len(v) == n for v in trovati.values()) and n > 1:
        soglia = n - 1
        risultati.approssimati = True
    per_pk = {d.pk: d for d in docs}
    elenco = []
    for pk, presi in trovati.items():
        if len(presi) < soglia:
            continue
        d = per_pk[pk]
        nel_titolo = all(esiti[i][pk][0] for i in presi)
        r = Risultato(doc=d, punteggio=0, nel_titolo=nel_titolo)
        r.punteggio += 25 * sum(1 for i in presi if esiti[i][pk][0])
        r.punteggio += 10 * len(presi)
        if usa_titolo and frase in intestazioni[pk]:
            r.punteggio += 40
        if usa_titolo and re.sub(r"[^a-z0-9]", "", frase) == re.sub(r"[^a-z0-9]", "", _piega(d.code)):
            r.punteggio += 80
        t = testo_di.get(pk)
        if t is not None:
            posizioni = [esiti[i][pk][1] for i in presi if esiti[i][pk][1]]
            if posizioni:
                r.occorrenze = min(len(p) for p in posizioni)
                r.punteggio += min(30, 3 * sum(len(p) for p in posizioni))
                if frase in t.piegato:
                    r.punteggio += 20
                _aggiungi_estratti(r, t, posizioni)
        elenco.append(r)
    elenco.sort(key=lambda r: (-r.punteggio, r.doc.code))
    risultati.extend(elenco[:MAX_RISULTATI])
    return risultati


@dataclass
class _Testo:
    hash: str
    testo: str
    piegato: str
    offset_pagine: list
    n_pagine: int | None
    n_caratteri: int


# Testi delle revisioni in vigore già «piegati» (minuscolo, senza accenti), per processo.
# Il corpus è piccolo (qualche centinaio di PDF): tenerlo in memoria evita di rileggerlo
# dal database a ogni ricerca. Una revisione si rilegge quando cambia l'hash del file.
_MEMO_TESTI: dict[int, _Testo] = {}


def _testi_piegati(rev_ids: list[int]) -> dict[int, _Testo]:
    from procedure_refresh.models import SgiTestoEstratto

    hash_attuali = {
        r: f"{h}:{n}"
        for r, h, n in SgiTestoEstratto.objects.filter(revision_id__in=rev_ids).values_list("revision_id", "file_hash", "n_caratteri")
    }
    da_leggere = [r for r, h in hash_attuali.items() if r not in _MEMO_TESTI or _MEMO_TESTI[r].hash != h]
    for i in range(0, len(da_leggere), 200):
        for t in SgiTestoEstratto.objects.filter(revision_id__in=da_leggere[i:i + 200]).only(
            "revision_id", "file_hash", "testo", "offset_pagine", "n_pagine", "n_caratteri"
        ):
            _MEMO_TESTI[t.revision_id] = _Testo(
                hash=f"{t.file_hash}:{t.n_caratteri}", testo=t.testo or "", piegato=_piega(t.testo or ""),
                offset_pagine=list(t.offset_pagine or []), n_pagine=t.n_pagine, n_caratteri=t.n_caratteri or len(t.testo or ""),
            )
    return {r: _MEMO_TESTI[r] for r in hash_attuali if r in _MEMO_TESTI}


def _aggiungi_estratti(r: Risultato, t, posizioni: list[list[int]]) -> None:
    """Estratti del testo: dove la parola più rara è vicina alle altre, al massimo uno per pagina."""
    rara = min(posizioni, key=len)
    altre = [p for p in posizioni if p is not rara]

    def vicine(pos):
        return sum(1 for p in altre if any(abs(x - pos) <= RAGGIO_VICINANZA for x in p))

    viste_pagine = set()
    for pos in sorted(rara, key=lambda x: (-vicine(x), x)):
        pagina = _pagina(t.offset_pagine or [], pos, t.n_pagine, t.n_caratteri or len(t.testo))
        if pagina in viste_pagine:
            continue
        viste_pagine.add(pagina)
        prima, trovato, dopo = _estratto(t.testo, pos, _fine_parola(t.testo, pos) - pos)
        r.estratti.append({"prima": prima, "trovato": trovato, "dopo": dopo, "sezione": _sezione(t.testo, pos), "pagina": pagina})
        if len(r.estratti) >= MAX_ESTRATTI:
            break


def indice_documento(rev, limite: int = 12) -> list[dict]:
    """Primi titoli di paragrafo del testo estratto, con la pagina: l'«indice» della scheda."""
    t = getattr(rev, "testo_estratto", None)
    if t is None or not t.testo:
        return []
    out, visti = [], set()
    for m in _SEZIONE_RE.finditer(t.testo):
        num = m.group(1).replace(" ", "")
        if num in visti or num.count(".") > 1:
            continue
        visti.add(num)
        fine = t.testo.find("\n", m.start())
        riga = t.testo[m.start():fine if fine >= 0 else len(t.testo)]
        titolo = re.sub(r"^\s*(?:#+\s*)?(?:§\s*)?\d+(?:\.\d+)*[.)]?\s*", "", riga).strip(" |#")
        if not titolo or len(titolo) < 3:
            continue
        out.append({
            "sezione": "§" + num.lstrip("§"),
            "titolo": titolo[:90],
            "pagina": _pagina(t.offset_pagine or [], m.start(), t.n_pagine, t.n_caratteri or len(t.testo)),
        })
        if len(out) >= limite:
            break
    return out


def radice_share() -> Path | None:
    raw = str(getattr(settings, "PROCEDURE_REFRESH_SGI_SHARE_ROOT", "") or "").strip()
    return Path(raw) if raw else None


def perche_file_non_apribile(percorso: str) -> str:
    """Perché il portale non riesce ad aprire il PDF: «permesso», «non_trovato» o «fuori_cartella».

    «permesso» = l'utente con cui gira il sito non può leggere la cartella SGI (la
    sincronizzazione può riuscirci lo stesso se gira con un altro utente).
    """
    radice = radice_share()
    try:
        if radice is not None:
            radice.stat()
            next(iter(radice.iterdir()), None)
    except PermissionError:
        return "permesso"
    except OSError:
        return "permesso"
    try:
        Path(percorso).stat()
    except PermissionError:
        return "permesso"
    except OSError:
        return "non_trovato"
    if radice is not None:
        try:
            Path(percorso).resolve().relative_to(radice.resolve())
        except (OSError, ValueError):
            return "fuori_cartella"
    return "non_trovato"


# ---------------------------------------------------------------------------
# Sapere: CN-SGI come catalogo della stanza e riquadro in home
# ---------------------------------------------------------------------------


def puo_aprire_libreria(request) -> bool:
    """Stessa decisione del middleware per la pagina della libreria (ACL v2)."""
    if not getattr(request.user, "is_authenticated", False):
        return False
    if request.user.is_superuser:
        return True
    try:
        from core.acl_v2 import check_acl_access_v2
        from core.legacy_utils import get_legacy_user

        return bool(check_acl_access_v2(
            path="/procedure-refresh/", legacy_user=get_legacy_user(request.user), django_user=request.user, request=request,
        ))
    except Exception:
        return False


def catalogo_sapere() -> dict:
    """Scheda di CN-SGI nella stessa forma dei cataloghi di Sapere (``core.sapere.schede_cataloghi``)."""
    from django.urls import reverse

    from procedure_refresh.models import SgiScaffale

    try:
        n = SgiScaffale.objects.filter(attivo=True).count()
    except Exception:
        n = 0
    return {
        "id": "cn-sgi",
        "href": reverse("procedure_refresh:libreria"),
        "titolo": "CN-SGI · Procedure",
        "descrizione": "Manuali, procedure, istruzioni e modelli del sistema di gestione integrato",
        "colore": "#002b5c",
        "sigla": "SGI",
        "copertina": "",
        "totale": n,
    }


def riquadro_sapere(request, limite: int = 5) -> dict | None:
    """Novità e letture da fare per il riquadro CN-SGI nella stanza Sapere della home (query leggere)."""
    from django.urls import reverse

    from procedure_refresh.models import ProcedureDocument

    if not puo_aprire_libreria(request):
        return None
    nuove = codici_nuove_revisioni()
    vis = Visibilita(request)
    docs = list(ProcedureDocument.objects.filter(is_active=True, code__in=list(nuove)[:200]).prefetch_related("revisions"))
    righe = []
    for d in sorted(docs, key=lambda x: nuove[x.code], reverse=True):
        rev = next((r for r in d.revisions.all() if r.is_current), None)
        if rev is None or not vis.puo_vedere(d):
            continue
        righe.append({"doc": d, "rev": rev, "href": reverse("procedure_refresh:libreria_documento", args=[d.pk])})
        if len(righe) >= limite:
            break
    return {
        "nuove": righe,
        "da_leggere": len(letture_da_fare(request.user)),
        "url": reverse("procedure_refresh:libreria"),
        "url_cerca": reverse("procedure_refresh:libreria_cerca"),
        "url_letture": reverse("procedure_refresh:my_assignments"),
    }
