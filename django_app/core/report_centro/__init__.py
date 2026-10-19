"""Centro report: catalogo, registro delle emissioni e profili di layout.

I report restano nei moduli che li generano. Questo pacchetto li mette in fila
in un unico posto (Amministrazione → Centro report) e aggiunge tre servizi
trasversali che i moduli ricevono senza modifiche:

- :mod:`.catalogo` — cosa esiste: ogni modulo dichiara i propri report in
  ``contenuti/<modulo>.py`` (nome, formati, route, dati personali, veste);
- :mod:`.registro` — chi ha scaricato cosa: un middleware registra ogni file
  generato (metadati + impronta SHA-256, mai il file);
- :mod:`.layout` — come appare: profili di stampa (logo, colori, piè di pagina,
  filigrana) applicati ai PDF costruiti con :mod:`core.pdf`.
"""
