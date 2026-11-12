"""Icone e loghi delle copertine delle librerie (CN-SGI, Gestione specifiche).

- ``ICONE``: pittogrammi a scelta per la copertina (stesso set del portale più alcuni di settore);
- :func:`svg_icona`: l'SVG da stampare sulla copertina;
- :func:`salva_logo` / :func:`risposta_logo`: il logo passa da ``core.copertine.prepara_copertina``
  (aperto con Pillow e ricodificato in JPEG, senza metadati), sta nello storage privato e si serve
  da una view del modulo. Niente SVG caricati dagli utenti.
"""
from __future__ import annotations

from django.utils.html import format_html
from django.utils.safestring import mark_safe

from core.icon_utils import _SEMANTIC_ICON_SVGS

_EXTRA = {
    "plane": '<path d="M2.5 13.5 10 11V5.5a2 2 0 0 1 4 0V11l7.5 2.5v2L14 14v4l2.5 1.5V21L12 20l-4.5 1v-1.5L10 18v-4l-7.5 1.5z"/>',
    "factory": '<path d="M3 21V10l5 3V10l5 3V10l5 3V4h3v17z"/><path d="M7 17h2M12 17h2M17 17h2"/>',
    "leaf": '<path d="M5 19c0-8 5-13 15-14-1 10-6 15-14 15"/><path d="M5 19c3-4 6-6 9-7"/>',
    "award": '<circle cx="12" cy="9" r="5.5"/><path d="M8.5 13.5 7 21l5-2.5 5 2.5-1.5-7.5"/>',
}

ICONE = (
    ("", "Nessuna"),
    ("shield-check", "Scudo"),
    ("award", "Certificazione"),
    ("book-open", "Libro"),
    ("file-check", "Documento verificato"),
    ("file-text", "Documento"),
    ("clipboard-list", "Elenco di controllo"),
    ("plane", "Aereo"),
    ("factory", "Fabbrica"),
    ("wrench", "Manutenzione"),
    ("tool", "Attrezzo"),
    ("siren", "Sicurezza"),
    ("heart", "Persone e salute"),
    ("users", "Persone"),
    ("leaf", "Ambiente"),
    ("recycle", "Riciclo"),
    ("zap", "Energia"),
    ("lock", "Riservato"),
    ("server", "Informatica"),
    ("cpu", "Elettronica"),
    ("database", "Dati"),
    ("globe", "Mondo"),
    ("briefcase", "Cliente"),
    ("package", "Fornitura"),
    ("layers", "Livelli"),
    ("star", "Stella"),
    ("flag", "Bandiera"),
)
NOMI = {k for k, _ in ICONE if k}


def svg_icona(nome: str, classe: str = "cop-ico") -> str:
    nome = str(nome or "").strip()
    if nome not in NOMI:
        return ""
    corpo = _EXTRA.get(nome) or _SEMANTIC_ICON_SVGS.get(nome, "")
    if not corpo:
        return ""
    return format_html(
        '<svg viewBox="0 0 24 24" class="{}" aria-hidden="true" focusable="false" fill="none" '
        'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{}</svg>',
        classe, mark_safe(corpo),
    )


def salva_logo(obj, upload, campo: str = "logo") -> None:
    """Ricodifica e salva il logo su ``obj.<campo>`` (senza salvare l'oggetto); ``CopertinaNonValida`` se il file non va."""
    from core.copertine import prepara_copertina

    nuovo = prepara_copertina(upload)
    togli_logo(obj, campo)
    getattr(obj, campo).save(nuovo.name, nuovo, save=False)


def togli_logo(obj, campo: str = "logo") -> None:
    vecchio = getattr(obj, campo, None)
    if vecchio:
        try:
            vecchio.delete(save=False)
        except OSError:
            pass
        setattr(obj, campo, None)


def risposta_logo(campo_file):
    """FileResponse del logo salvato (404 se manca), con cache breve nel browser."""
    from django.http import FileResponse, Http404

    if not campo_file:
        raise Http404("Nessun logo.")
    try:
        fh = campo_file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Logo non trovato.")
    resp = FileResponse(fh, content_type="image/jpeg")
    resp["Cache-Control"] = "private, max-age=3600"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
