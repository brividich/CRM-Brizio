"""Cataloghi della stanza «Sapere»: chi vede cosa e come si mostra una voce.

Funzioni pure usate dalle pagine ``/sapere/``, dalla home e dalla gestione
admin. La visibilità è decisa qui, lato server, per ogni catalogo e per ogni
voce:

- catalogo: ``is_visible`` e ruoli (nessun ruolo = tutti; l'amministratore
  vede anche i cataloghi nascosti solo nella gestione, non nelle pagine);
- voce «risorsa»: stesse regole della bacheca (``link_visible_to_role``);
- voce «guida»: la guida deve esistere; quelle ``solo_admin`` solo agli
  amministratori del Centro guide;
- voce «collegamento»: sempre mostrata; la pagina di destinazione applica
  i suoi permessi quando la si apre.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.urls import reverse

from core.hub_bacheca import link_visible_to_role
from core.models import Catalogo, CatalogoVoce, HubLink

COLORE_DEFAULT = "#1f4f86"
COLORE_GUIDE = "#0f766e"
COLORE_COLLEGAMENTI = "#475569"

_KIND_LABEL = {
    HubLink.KIND_FILE: "Documento",
    HubLink.KIND_URL: "Collegamento",
    HubLink.KIND_INTERNAL: "Pagina del portale",
}


@dataclass(frozen=True)
class Identita:
    role_id: int | None
    is_admin: bool
    guide_admin: bool


def identita(request) -> Identita:
    from core.guide_moduli import puo_vedere_admin
    from core.legacy_utils import get_legacy_user, is_legacy_admin

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = bool(request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False))
    return Identita(
        role_id=getattr(legacy_user, "ruolo_id", None),
        is_admin=is_admin,
        guide_admin=is_admin or puo_vedere_admin(request),
    )


def sigla_da_titolo(titolo: str, sigla: str = "") -> str:
    """Sigla della copertina: quella impostata, altrimenti le iniziali del titolo."""
    if (sigla or "").strip():
        return sigla.strip()[:8]
    parole = [p for p in (titolo or "").replace("-", " ").split() if p[:1].isalnum()]
    if not parole:
        return "?"
    if len(parole) == 1:
        return parole[0][:4].upper()
    return "".join(p[0] for p in parole[:3]).upper()


def url_collegamento_valido(url: str) -> bool:
    """Pagina del portale («/…», non «//») o indirizzo http(s)."""
    url = (url or "").strip()
    if url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return True
    return url.lower().startswith(("https://", "http://"))


def url_copertina(tipo: str, obj) -> str:
    """Indirizzo protetto della copertina, con versione per la cache del browser."""
    if not getattr(obj, "copertina", None):
        return ""
    # Ogni copertina caricata ha un nome nuovo (uuid): cambia l'indirizzo e la cache si rinnova.
    versione = obj.copertina.name.rsplit("/", 1)[-1].split(".", 1)[0][:12]
    return f"{reverse('sapere_copertina', args=[tipo, obj.pk])}?v={versione}"


def catalogo_visibile(catalogo: Catalogo, ident: Identita) -> bool:
    if not catalogo.is_visible:
        return False
    if ident.is_admin:
        return True
    ruoli = [a.legacy_role_id for a in catalogo.role_accesses.all()]
    if not ruoli:
        return True
    return ident.role_id is not None and ident.role_id in ruoli


def cataloghi_visibili(ident: Identita) -> list[Catalogo]:
    qs = (Catalogo.objects.filter(is_visible=True)
          .prefetch_related("role_accesses")
          .order_by("ordine", "titolo", "id"))
    return [c for c in qs if catalogo_visibile(c, ident)]


def _voce_risorsa(voce: CatalogoVoce, ident: Identita) -> dict | None:
    link = voce.hub_link
    if link is None or not link_visible_to_role(link, ident.role_id, ident.is_admin):
        return None
    titolo = voce.titolo or link.title
    return {
        "titolo": titolo,
        "descrizione": voce.descrizione or link.description,
        "sigla": sigla_da_titolo(titolo, voce.sigla or link.sigla),
        "etichetta": _KIND_LABEL.get(link.kind, ""),
        "href": link.resolve_href(),
        "nuova_scheda": bool(link.open_in_new_tab or link.kind == HubLink.KIND_URL),
        "copertina": url_copertina("voce", voce) or url_copertina("risorsa", link),
        "colore": link.category.colore or COLORE_DEFAULT,
    }


def _voce_guida(voce: CatalogoVoce, ident: Identita) -> dict | None:
    from core import guide_moduli

    guida = guide_moduli.per_slug(voce.guida_slug)
    if guida is None or (guida["solo_admin"] and not ident.guide_admin):
        return None
    titolo = voce.titolo or guida["titolo"]
    return {
        "titolo": titolo,
        "descrizione": voce.descrizione or guida["sintesi"],
        "sigla": sigla_da_titolo(titolo, voce.sigla),
        "etichetta": "Guida",
        "href": reverse("guida_modulo", args=[guida["slug"]]),
        "nuova_scheda": False,
        "copertina": url_copertina("voce", voce),
        "colore": COLORE_GUIDE,
    }


def _voce_collegamento(voce: CatalogoVoce, ident: Identita) -> dict | None:
    if not url_collegamento_valido(voce.url):
        return None
    esterno = not voce.url.startswith("/")
    return {
        "titolo": voce.titolo or voce.url,
        "descrizione": voce.descrizione,
        "sigla": sigla_da_titolo(voce.titolo, voce.sigla),
        "etichetta": "Collegamento" if esterno else "Pagina del portale",
        "href": voce.url,
        "nuova_scheda": esterno,
        "copertina": url_copertina("voce", voce),
        "colore": COLORE_COLLEGAMENTI,
    }


_COSTRUTTORI = {
    CatalogoVoce.TIPO_RISORSA: _voce_risorsa,
    CatalogoVoce.TIPO_GUIDA: _voce_guida,
    CatalogoVoce.TIPO_COLLEGAMENTO: _voce_collegamento,
}


def voci_visibili(catalogo: Catalogo, ident: Identita) -> list[dict]:
    voci = (catalogo.voci.select_related("hub_link__category")
            .prefetch_related("hub_link__role_accesses")
            .order_by("ordine", "id"))
    out = []
    for voce in voci:
        costruttore = _COSTRUTTORI.get(voce.tipo)
        dati = costruttore(voce, ident) if costruttore else None
        if dati:
            dati["id"] = voce.pk
            out.append(dati)
    return out


def scheda_catalogo(catalogo: Catalogo, ident: Identita, *, con_voci: bool = False) -> dict:
    """Dati di un catalogo per le copertine (home e indice) e per la sua pagina."""
    voci = voci_visibili(catalogo, ident)
    scheda = {
        "id": catalogo.pk,
        "titolo": catalogo.titolo,
        "slug": catalogo.slug,
        "descrizione": catalogo.descrizione,
        "colore": catalogo.colore or COLORE_DEFAULT,
        "copertina": url_copertina("catalogo", catalogo),
        "sigla": sigla_da_titolo(catalogo.titolo),
        "totale": len(voci),
        "href": reverse("sapere_catalogo", args=[catalogo.slug]),
    }
    if con_voci:
        scheda["voci"] = voci
    return scheda


def schede_cataloghi(ident: Identita) -> list[dict]:
    """Cataloghi visibili con almeno una voce visibile."""
    return [s for s in (scheda_catalogo(c, ident) for c in cataloghi_visibili(ident)) if s["totale"]]


def guide_disponibili(ident: Identita) -> list[dict]:
    """Guide del Centro guide che si possono aggiungere a un catalogo (per la gestione)."""
    from core import guide_moduli

    return [g for g in guide_moduli.tutte() if ident.guide_admin or not g["solo_admin"]]

