"""Locandina stampabile (A4) di un corso o di un'edizione, con il QR da inquadrare.

Il QR porta dove la persona deve andare davvero:
- edizione online (slide + test) o corso online con link aperto attivo → il **link aperto**
  (matricola e cognome, niente password; vale anche per chi non ha l'utente del portale);
- edizione online senza link aperto → la lezione nel portale (serve l'accesso);
- edizione in aula → il **QR d'aula** per firmare ingresso e uscita il giorno della lezione.
Con ``?qr=aperto|aula|portale`` si sceglie un QR diverso quando ce n'è più di uno.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe

from .models_formazione import TrainingCourse, TrainingSession
from .views import _helpers


def _svg_qr(url: str) -> str:
    """QR in SVG (nitido in stampa a qualunque dimensione)."""
    import qrcode
    import qrcode.image.svg

    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2,
                         image_factory=qrcode.image.svg.SvgPathImage)
    code.add_data(url)
    code.make(fit=True)
    svg = code.make_image().to_string(encoding="unicode")
    return svg[svg.find("<svg"):] if "<svg" in svg else svg


def _base(request, path: str) -> str:
    from django.conf import settings
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    return base + path if base else request.build_absolute_uri(path)


def _qr_possibili(request, corso, sessione=None) -> dict:
    """{chiave: (url, titolo, istruzioni)} dei QR che hanno senso per questa locandina."""
    from .views_elearning import link_pubblico_info

    out = {}
    online = sessione is None or sessione.modalita == "ONLINE" or bool(
        getattr(getattr(sessione, "lezione_online", None), "pubblicata_il", None)
        and not getattr(sessione.lezione_online, "test_in_aula", False))
    info = link_pubblico_info(request, corso)
    if online and info and info.get("funziona"):
        out["aperto"] = (info["url"], "Inquadra e inizia",
                         "Si apre sul telefono: scrivi nome, cognome e matricola. Niente password. "
                         "Puoi interrompere e riprendere quando vuoi.")
    if sessione is not None and online and getattr(sessione, "lezione_online", None):
        out["portale"] = (_base(request, reverse("anagrafica:sessione_online_player", args=[sessione.pk])),
                          "Inquadra e accedi al portale", "Entra con le tue credenziali del portale: trovi la "
                          "lezione anche in «I miei corsi online».")
    if sessione is not None and sessione.modalita != "ONLINE":
        from .services import formazione_aula as aula
        out["aula"] = (_base(request, reverse("corso_aperto:aula", args=[aula.token(sessione)])),
                       "Il giorno del corso, inquadra per firmare",
                       "Da 30 minuti prima a 30 minuti dopo la lezione: matricola e cognome, firma l'ingresso; "
                       "a fine lezione firma l'uscita dallo stesso telefono.")
    return out


def _render(request, corso, sessione=None):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        if sessione is not None:
            return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione.pk)
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso.pk)
    qr = _qr_possibili(request, corso, sessione)
    scelta = request.GET.get("qr") if request.GET.get("qr") in qr else next(iter(qr), "")
    giornate = list(sessione.lezioni.order_by("data", "ora_inizio")) if sessione is not None else []
    cfg = getattr(sessione, "lezione_online", None) if sessione is not None else None
    url, titolo_qr, istruzioni = qr.get(scelta, ("", "", ""))
    return render(request, "anagrafica/pages/formazione_locandina.html", {
        "corso": corso, "sessione": sessione, "giornate": giornate, "cfg": cfg,
        "qr_svg": mark_safe(_svg_qr(url)) if url else "", "qr_url": url, "qr_titolo": titolo_qr,
        "qr_istruzioni": istruzioni, "qr_scelta": scelta,
        "qr_altri": [(k, v[1]) for k, v in qr.items()],
        "online": bool(sessione is None or sessione.modalita == "ONLINE" or cfg),
        "torna": (reverse("anagrafica:formazione_sessione_detail", args=[sessione.pk]) if sessione is not None
                  else reverse("anagrafica:formazione_corso_detail", args=[corso.pk])),
    })


@login_required
def sessione_locandina(request, sessione_id: int):
    sessione = get_object_or_404(TrainingSession.objects.select_related("corso", "corso__tipo"), pk=sessione_id)
    return _render(request, sessione.corso, sessione)


@login_required
def corso_locandina(request, corso_id: int):
    corso = get_object_or_404(TrainingCourse.objects.select_related("tipo"), pk=corso_id)
    return _render(request, corso)
