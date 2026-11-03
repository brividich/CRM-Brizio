"""Locandina con QR del Suggestion Corner, da stampare e appendere in bacheca.

Il QR porta al form pubblico (``/suggestion-corner/nuova/``) ed è sempre al
centro della pagina, alla stessa altezza in ogni preset: i testi del preset
(``SuggestionCornerLocandina``) riempiono solo la fascia sopra e quella sotto,
e i limiti di lunghezza dei campi tengono l'impaginazione stabile. Il QR è
disegnato a moduli vettoriali, quindi resta nitido anche stampato in A3.
"""
from __future__ import annotations

import io
from django.conf import settings
from django.urls import reverse

#: Colori per tema: (fascia/testi forti, accento, fondo chiaro dell'accento).
TEMI = {
    "hub": ("#002b5c", "#ff6b00", "#fff4ed"),
    "verde": ("#14532d", "#16a34a", "#ecfdf3"),
    "rosso": ("#7f1d1d", "#dc2626", "#fef2f2"),
    "grigio": ("#1f2937", "#4b5563", "#f3f4f6"),
}

def url_form_pubblico(request=None) -> str:
    """Indirizzo codificato nel QR: config del modulo, poi SITE_URL, poi l'host della richiesta."""
    from .models import SuggestionCornerConfig

    configurato = (SuggestionCornerConfig.load().url_pubblico_form or "").strip()
    if configurato:
        return configurato
    path = reverse("suggestion_corner:nuova")
    site_url = str(getattr(settings, "SITE_URL", "") or "").strip().rstrip("/")
    if site_url:
        return f"{site_url}{path}"
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def _righe(testo: str, font: str, size: float, larghezza: float, max_righe: int) -> list[str]:
    """A capo per parole entro ``larghezza``; oltre ``max_righe`` tronca con «…»."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    righe: list[str] = []
    corrente = ""
    for parola in (testo or "").split():
        prova = f"{corrente} {parola}".strip()
        if stringWidth(prova, font, size) <= larghezza or not corrente:
            corrente = prova
        else:
            righe.append(corrente)
            corrente = parola
    if corrente:
        righe.append(corrente)
    if len(righe) > max_righe:
        righe = righe[:max_righe]
        ultima = righe[-1]
        while ultima and stringWidth(ultima + "…", font, size) > larghezza:
            ultima = ultima[:-1]
        righe[-1] = ultima.rstrip() + "…"
    return righe


def _adatta(testo: str, font: str, size: float, larghezza: float, max_righe: int, minimo: float):
    """Riduce il corpo finché il testo sta in ``max_righe`` senza troncare (fino a ``minimo``)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    while size > minimo:
        parole = (testo or "").split()
        if all(stringWidth(p, font, size) <= larghezza for p in parole):
            righe = _righe(testo, font, size, larghezza, max_righe + 1)
            if len(righe) <= max_righe:
                return righe, size
        size -= 1
    return _righe(testo, font, minimo, larghezza, max_righe), minimo


def _disegna_qr(c, url: str, x: float, y: float, lato: float, colore) -> None:
    import qrcode

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(url)
    qr.make(fit=True)
    matrice = qr.get_matrix()
    n = len(matrice)
    modulo = lato / n
    c.setFillColor(colore)
    # Un solo tracciato con i moduli contigui di una riga uniti, riempito e
    # ripassato con un filo dello stesso colore: copre i filetti bianchi che
    # i visualizzatori PDF lasciano fra due righe adiacenti.
    c.setStrokeColor(colore)
    c.setLineWidth(modulo * 0.08)
    c.setLineJoin(0)
    tracciato = c.beginPath()
    for r, riga in enumerate(matrice):
        col = 0
        while col < n:
            if not riga[col]:
                col += 1
                continue
            inizio = col
            while col < n and riga[col]:
                col += 1
            tracciato.rect(x + inizio * modulo, y + lato - (r + 1) * modulo,
                           (col - inizio) * modulo, modulo)
    c.drawPath(tracciato, stroke=1, fill=1)


def render_locandina_pdf(dati, url: str) -> bytes:
    """PDF della locandina. ``dati`` è un ``SuggestionCornerLocandina`` (anche non salvato)."""
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.pagesizes import A3, A4
    from reportlab.pdfgen import canvas

    pagina = A3 if dati.formato == "A3" else A4
    W, H = pagina
    s = W / A4[0]  # scala: tutto è progettato su A4 e cresce col foglio
    forte, accento, chiaro = (HexColor(v) for v in TEMI.get(dati.tema, TEMI["hub"]))
    grigio = HexColor("#6b7280")
    margine = 44 * s
    utile = W - 2 * margine

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagina)
    c.setTitle(f"Locandina Suggestion Corner — {dati.nome or 'anteprima'}")
    c.setAuthor("NOVICROM HUB")

    # --- Fascia alta: titolo e sottotitolo ---------------------------------
    fascia = 218 * s
    c.setFillColor(forte)
    c.rect(0, H - fascia, W, fascia, stroke=0, fill=1)
    c.setFillColor(accento)
    c.rect(0, H - fascia - 9 * s, W, 9 * s, stroke=0, fill=1)

    righe_t, size_t = _adatta(dati.titolo, "Helvetica-Bold", 50 * s, utile, 2, 30 * s)
    righe_s, size_s = _adatta(dati.sottotitolo, "Helvetica", 17 * s, utile, 2, 12 * s)
    alto_t = len(righe_t) * size_t * 1.08
    alto_s = len(righe_s) * size_s * 1.3 + (14 * s if righe_s else 0)
    y = H - fascia / 2 + (alto_t + alto_s) / 2 - size_t * 0.8
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", size_t)
    for riga in righe_t:
        c.drawCentredString(W / 2, y, riga)
        y -= size_t * 1.08
    if righe_s:
        y -= 14 * s - size_t * 0.08
        c.setFillColor(HexColor("#e5e7eb"))
        c.setFont("Helvetica", size_s)
        for riga in righe_s:
            c.drawCentredString(W / 2, y, riga)
            y -= size_s * 1.3

    # --- QR al centro: posizione fissa in ogni preset ----------------------
    lato = 250 * s
    cornice = 22 * s
    qr_x = (W - lato) / 2
    qr_y = H / 2 - lato / 2 - 10 * s
    c.setFillColor(white)
    c.setStrokeColor(accento)
    c.setLineWidth(4 * s)
    c.roundRect(qr_x - cornice, qr_y - cornice, lato + 2 * cornice, lato + 2 * cornice, 18 * s,
                stroke=1, fill=1)
    _disegna_qr(c, url, qr_x, qr_y, lato, forte)

    if dati.invito:
        c.setFillColor(forte)
        c.setFont("Helvetica-Bold", 19 * s)
        c.drawCentredString(W / 2, qr_y + lato + cornice + 18 * s, dati.invito)
    y = qr_y - cornice - 20 * s
    if dati.mostra_indirizzo:
        c.setFillColor(grigio)
        c.setFont("Helvetica", 10.5 * s)
        c.drawCentredString(W / 2, y, url)
        y -= 14 * s

    # --- Passi numerati ----------------------------------------------------
    passi = dati.elenco_passi
    y -= 30 * s
    if passi:
        colonna = utile / len(passi)
        raggio = 15 * s
        for i, passo in enumerate(passi):
            cx = margine + colonna * i + colonna / 2
            c.setFillColor(accento)
            c.circle(cx, y, raggio, stroke=0, fill=1)
            c.setFillColor(white)
            c.setFont("Helvetica-Bold", 15 * s)
            c.drawCentredString(cx, y - 5.3 * s, str(i + 1))
            c.setFillColor(HexColor("#1f2937"))
            c.setFont("Helvetica", 12.5 * s)
            ty = y - raggio - 18 * s
            for riga in _righe(passo, "Helvetica", 12.5 * s, colonna - 16 * s, 2):
                c.drawCentredString(cx, ty, riga)
                ty -= 15.5 * s

    # --- Nota (anonimato): appoggiata sopra il piede -----------------------
    if dati.nota:
        righe_n = _righe(dati.nota, "Helvetica-Bold", 13.5 * s, utile - 40 * s, 2)
        alto = len(righe_n) * 18 * s + 22 * s
        base = 80 * s
        c.setFillColor(chiaro)
        c.roundRect(margine, base, utile, alto, 12 * s, stroke=0, fill=1)
        c.setFillColor(forte)
        c.setFont("Helvetica-Bold", 13.5 * s)
        ty = base + alto - 11 * s - 13.5 * s * 0.8
        for riga in righe_n:
            c.drawCentredString(W / 2, ty, riga)
            ty -= 18 * s

    # --- Piede: marchio e testo ---------------------------------------------
    piede_y = 34 * s
    c.setStrokeColor(HexColor("#e5e7eb"))
    c.setLineWidth(1 * s)
    c.line(margine, piede_y + 26 * s, W - margine, piede_y + 26 * s)
    c.setFillColor(forte)
    c.setFont("Helvetica-Bold", 12 * s)
    c.drawString(margine, piede_y + 4 * s, "NOVICROM")
    if dati.piede:
        c.setFillColor(grigio)
        c.setFont("Helvetica", 10 * s)
        c.drawRightString(W - margine, piede_y + 4 * s, dati.piede)

    c.showPage()
    c.save()
    return buf.getvalue()
