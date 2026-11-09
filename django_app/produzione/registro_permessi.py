"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md. Nella matrice dei ruoli:

- «Vedere»: elenco degli OP e scheda (``produzione.op.view``);
- «Creare» / «Modificare» / «Cancellare»: documenti di produzione e nuovo OP
  (``produzione.documenti.manage``, ``produzione.op.manage``);
- «Impostazioni del modulo»: tipi di documento (``produzione.impostazioni.manage``,
  dichiarato in ``core/permessi/impostazioni.py``).

Il suffisso ``manage`` verrebbe letto come amministrazione: le capacità sono forzate.
"""
from core.permessi.registro import ModuloPermessi, registra_modulo


def proprietario_documento(documento):
    from core.permessi import legacy_id_da_user_id

    return legacy_id_da_user_id(getattr(documento, "creato_da_id", None))


registra_modulo(ModuloPermessi(
    chiave="produzione",
    nome="Ordini di produzione",
    descrizione="Gli OP con i documenti di produzione: documenti registrati, FAI, programmi CAM e CMM, anomalie.",
    area="Produzione",
    app="produzione",
    moduli_acl=("produzione",),
    capacita_forzate=(
        ("produzione.op.view", "lettura"),
        ("produzione.documenti.manage", "modifica"),
        ("produzione.op.manage", "modifica"),
    ),
    proprietario=proprietario_documento,
))
