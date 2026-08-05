"""Header delle risposte raggiungibili **senza login**.

Il portale espone una manciata di superfici fuori dal perimetro autenticato
(vedi ``MIDDLEWARE_EXEMPT_PREFIXES``): landing dei QR fisici, form pubblici,
e soprattutto le pagine **a token** delle approvazioni e delle azioni via mail.
Lì non passa nessun middleware applicativo, quindi ogni default permissivo del
browser resta tale.

Due header valgono più degli altri:

* ``Referrer-Policy: no-referrer`` — su una pagina il cui **URL contiene il
  token**, qualunque risorsa esterna o link in uscita lo farebbe viaggiare
  nell'header ``Referer`` verso terzi. È il motivo principale per cui questo
  modulo esiste.
* ``Cache-Control: no-store`` — una pagina a token (o una scheda di sicurezza
  revisionata) non deve restare nella cache del browser di un dispositivo
  condiviso, che in officina è la norma.

La CSP globale non si tocca: qui si aggiungono solo header di risposta.

**Limite noto**: il decoratore agisce sulla risposta che la view *restituisce*.
Se la view solleva ``Http404`` (token inesistente o scaduto), la risposta la
produce il gestore d'errore di Django e questi header non ci finiscono. È
accettabile: quella pagina non contiene né il contenuto protetto né link in
uscita, quindi non c'è nulla da far trapelare. Coprire anche quel caso
richiederebbe un middleware, che è esattamente ciò che qui si evita.
"""
from __future__ import annotations

from functools import wraps

HEADER_PUBBLICI = {
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store, max-age=0",
}


def blinda_risposta_pubblica(response):
    """Applica gli header alla risposta e la restituisce.

    Non sovrascrive un ``Cache-Control`` già impostato dalla view: se qualcuno
    ha deciso una politica di cache diversa, l'avrà fatto con cognizione.
    """
    for nome, valore in HEADER_PUBBLICI.items():
        if nome == "Cache-Control" and response.has_header("Cache-Control"):
            continue
        response[nome] = valore
    return response


def risposta_pubblica(view_func):
    """Decoratore per le view sotto un prefisso esente da autenticazione."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        return blinda_risposta_pubblica(view_func(request, *args, **kwargs))

    return _wrapped
