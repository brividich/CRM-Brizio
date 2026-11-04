"""Allineamento automatico di un livello sulla pianta base.

Le piante dei servizi vengono dallo stesso disegno della pianta base: i muri
sono gli stessi, cambiano rotazione (di solito 90°), scala e ritaglio. Qui si
cerca la similitudine che porta i muri del livello sopra quelli della base:

1. dalle due immagini si tengono i tratti scuri e grigi (muri, paratie), non i
   simboli colorati; dal livello si tolgono legenda e cartiglio;
2. per ognuna delle quattro rotazioni e per una serie di scale si prova ogni
   spostamento in un colpo solo (correlazione con la FFT) su una versione piccola;
3. i candidati migliori si rifiniscono su una versione più grande (scala,
   piccola rotazione, spostamento).

Il risultato sono due coppie di punti, come quelle cliccate a mano in «Livello
e scala», più un punteggio: la quota di muri del livello che cade su un muro
della base. Sotto la soglia l'allineamento non si salva da solo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

SOGLIA_BUONO = 0.50  # sotto: i muri non combaciano, l'allineamento si fa a mano

_LATO_GROSSO = 220  # px del lato lungo per la ricerca grossolana
_LATO_FINE = 700  # px del lato lungo per la rifinitura
_LATO_PIENO = 1600  # px del lato lungo per l'ultimo ritocco


@dataclass
class EsitoAllineamento:
    punti: list[list[float]]  # [[x, y, xb, yb], [x, y, xb, yb]] in %
    punteggio: float  # 0..1
    rotazione: float  # gradi
    scala: float  # px base / px livello (a pari lato lungo)

    @property
    def buono(self) -> bool:
        return self.punteggio >= SOGLIA_BUONO


def maschera_tratti(img, escludi=()) -> np.ndarray:
    """Pixel dei tratti scuri o grigi (non colorati) di un'immagine PIL; ``escludi`` = riquadri in %."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.int16)
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    m = (mx < 215) & ((mx - mn) < 45)
    h, w = m.shape
    bordo = max(3, int(0.006 * max(h, w)))  # anche la cornice della legenda, che sta sul bordo del riquadro
    for r in escludi or ():
        x0, x1 = int(max(0, r.x0) * w / 100) - bordo, int(min(100, r.x1) * w / 100) + 1 + bordo
        y0, y1 = int(max(0, r.y0) * h / 100) - bordo, int(min(100, r.y1) * h / 100) + 1 + bordo
        m[max(0, y0):y1, max(0, x0):x1] = False
    return m


def _riduci(m: np.ndarray, lato: int) -> tuple[np.ndarray, float]:
    """Riduce la maschera tenendo un pixel acceso se nel blocco c'è un tratto (le linee sottili non spariscono)."""
    h, w = m.shape
    k = max(1, math.ceil(max(h, w) / lato))
    hh, ww = (h // k) * k, (w // k) * k
    if hh == 0 or ww == 0:
        return m.copy(), 1.0
    r = m[:hh, :ww].reshape(hh // k, k, ww // k, k).any(axis=(1, 3))
    return r, float(k)


def _dilata(m: np.ndarray) -> np.ndarray:
    d = m.copy()
    d[1:, :] |= m[:-1, :]
    d[:-1, :] |= m[1:, :]
    d[:, 1:] |= m[:, :-1]
    d[:, :-1] |= m[:, 1:]
    return d


def _vicinanza(m: np.ndarray, raggio: int) -> np.ndarray:
    """1 sul tratto, scende a 0 a ``raggio`` pixel: premia i punti che cadono vicino a un muro."""
    acc = m.astype(np.float32)
    cur = m
    for _ in range(raggio):
        cur = _dilata(cur)
        acc += cur
    return acc / (raggio + 1)


def _punti(m: np.ndarray, massimo: int, seme: int = 7) -> np.ndarray:
    ys, xs = np.nonzero(m)
    p = np.stack([xs, ys], axis=1).astype(np.float32)
    if len(p) > massimo:
        p = p[np.random.default_rng(seme).choice(len(p), massimo, replace=False)]
    return p


def _ruota(p: np.ndarray, gradi: float) -> np.ndarray:
    a = math.radians(gradi)
    c, s = math.cos(a), math.sin(a)
    return np.stack([c * p[:, 0] - s * p[:, 1], s * p[:, 0] + c * p[:, 1]], axis=1)


def _punteggio(vic: np.ndarray, q: np.ndarray) -> float:
    h, w = vic.shape
    xi = np.rint(q[:, 0]).astype(np.int64)
    yi = np.rint(q[:, 1]).astype(np.int64)
    ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
    if not ok.any():
        return 0.0
    return float(vic[yi[ok], xi[ok]].sum() / len(q))


def _copertura(vic_liv: np.ndarray, mb: np.ndarray, par) -> float:
    """Il contrario del punteggio: i muri della base, nella zona coperta dal livello, cadono su un muro del livello?

    Si guarda nella risoluzione del livello: un livello rimpicciolito fino a cadere tutto su pochi
    muri della base ha un punteggio alto, ma i muri della base riportati sul livello finiscono nel vuoto.
    """
    r, sc, tx, ty = par
    hl, wl = vic_liv.shape
    ys, xs = np.nonzero(mb)
    p = np.stack([xs, ys], axis=1).astype(np.float32)
    q = _ruota((p - np.array([tx, ty])) / sc, -r)
    ok = (q[:, 0] >= 0) & (q[:, 0] < wl - 0.5) & (q[:, 1] >= 0) & (q[:, 1] < hl - 0.5)
    if ok.sum() < 20:
        return 0.0
    q = q[ok]
    if len(q) > 8000:
        q = q[np.random.default_rng(1).choice(len(q), 8000, replace=False)]
    return _punteggio(vic_liv, q)


def _f(vic: np.ndarray, mb: np.ndarray, vic_liv: np.ndarray, pts: np.ndarray, par) -> float:
    r, sc, tx, ty = par
    pr = _punteggio(vic, _ruota(pts, r) * sc + np.array([tx, ty]))
    rc = _copertura(vic_liv, mb, par)
    return math.sqrt(max(pr, 0) * max(rc, 0))


def _miglior_spostamento(vic: np.ndarray, q: np.ndarray) -> tuple[float, float, float]:
    """Spostamento (dx, dy) che massimizza la somma di ``vic`` sui punti ``q``, con la FFT."""
    h, w = vic.shape
    q = q - q.min(axis=0)
    qw, qh = int(math.ceil(q[:, 0].max())) + 1, int(math.ceil(q[:, 1].max())) + 1
    H = 1 << int(math.ceil(math.log2(h + qh)))
    W = 1 << int(math.ceil(math.log2(w + qw)))
    a = np.zeros((H, W), np.float32)
    a[:h, :w] = vic
    b = np.zeros((H, W), np.float32)
    np.add.at(b, (np.rint(q[:, 1]).astype(int), np.rint(q[:, 0]).astype(int)), 1.0)
    corr = np.fft.irfft2(np.fft.rfft2(a) * np.conj(np.fft.rfft2(b)), s=(H, W))
    # spostamenti negativi: il livello sporge a sinistra/sopra della base
    iy, ix = np.unravel_index(int(np.argmax(corr)), corr.shape)
    dy = iy - H if iy > H - qh else iy
    dx = ix - W if ix > W - qw else ix
    return float(dx), float(dy), float(corr[iy, ix] / len(q))


def _rifinisci(vic, pts, par0, passi, max_rot, max_scala):
    """Ricerca locale di (rotazione, scala, dx, dy) intorno a ``par0``, senza allontanarsi troppo."""
    def porta(p, par):
        r, sc, tx, ty = par
        return _ruota(p, r) * sc + np.array([tx, ty])

    par = list(par0)
    val = _punteggio(vic, porta(pts, par))
    passi = list(passi)
    for _ in range(120):
        meglio = False
        for i in range(4):
            for segno in (1, -1):
                prova = list(par)
                prova[i] += segno * passi[i]
                # niente derive verso un livello minuscolo o girato
                if abs(prova[0] - par0[0]) > max_rot or abs(prova[1] / par0[1] - 1) > max_scala:
                    continue
                v = _punteggio(vic, porta(pts, prova))
                if v > val + 1e-6:
                    par, val, meglio = prova, v, True
        if not meglio:
            passi = [p / 2 for p in passi]
            if passi[2] < 0.2:
                break
    return par


def allinea(img_livello, img_base, escludi=()) -> EsitoAllineamento | None:
    """Similitudine livello → base cercata sui muri; ``None`` se una delle due immagini non ha tratti."""
    ml = maschera_tratti(img_livello, escludi)
    mb = maschera_tratti(img_base)
    if ml.sum() < 200 or mb.sum() < 200:
        return None
    hl0, wl0 = ml.shape
    hb0, wb0 = mb.shape

    # --- ricerca grossolana: 4 rotazioni x scale, spostamento con la FFT ------------
    gb, kb = _riduci(mb, _LATO_GROSSO)
    gl, kl = _riduci(ml, _LATO_GROSSO)
    vic_g = _vicinanza(gb, 2)
    pl = _punti(gl, 3000)
    ys, xs = np.nonzero(gb)
    lato_base = max(xs.max() - xs.min(), ys.max() - ys.min()) + 1
    grezzi = []
    for rot in (0, 90, 180, 270):
        pr = _ruota(pl, rot)
        lato_liv = float(max(np.ptp(pr[:, 0]), np.ptp(pr[:, 1]))) + 1
        for f in np.geomspace(0.1, 1.3, 96):
            s = f * lato_base / lato_liv
            q = pr * s
            dx, dy, _ = _miglior_spostamento(vic_g, q)
            t = -q.min(axis=0) + np.array([dx, dy])
            grezzi.append((_punteggio(vic_g, q + t), rot, s, t))
        vic_gl = _vicinanza(gl, 2)
    # per ogni rotazione le scale migliori, ritoccate già qui: la griglia delle scale è larga
    # e su piante con pochi muri lunghi un 2% di scala sbagliata basta a perdere la soluzione giusta
    candidati = []
    # il punteggio da solo premia un livello rimpicciolito su pochi muri: si ordina con la copertura
    grezzi = [(_f(vic_g, gb, vic_gl, pl, (rot, s, t[0], t[1])), rot, s, t) for _p, rot, s, t in grezzi]
    for rot in (0, 90, 180, 270):
        della_rot = sorted((c for c in grezzi if c[1] == rot), key=lambda c: -c[0])
        scelte = []
        for c in della_rot:
            if all(abs(c[2] / x[2] - 1) > 0.06 for x in scelte):
                scelte.append(c)
            if len(scelte) == 6:
                break
        for _p, _r, s, t in scelte:
            par = _rifinisci(vic_g, pl, [float(rot), s, float(t[0]), float(t[1])], [1.0, s * 0.01, 1.0, 1.0], 4.0, 0.08)
            candidati.append((_f(vic_g, gb, vic_gl, pl, par), par[0], par[1], np.array(par[2:4])))
    candidati.sort(key=lambda c: -c[0])

    # --- rifinitura su un'immagine più grande, vicino a ogni candidato --------------
    fb, kfb = _riduci(mb, _LATO_FINE)
    fl, kfl = _riduci(ml, _LATO_FINE)
    vic_f = _vicinanza(fb, 2)
    vic_larga = _vicinanza(fb, 5)  # prima passata: bacino largo, non si ferma sul muro parallelo sbagliato
    pf = _punti(fl, 6000, seme=11)
    vic_fl = _vicinanza(fl, 2)
    conv_b = kb / kfb
    conv_l = kfl / kl

    def porta(p, par):
        r, sc, tx, ty = par
        return _ruota(p, r) * sc + np.array([tx, ty])

    migliore = None
    visti = []
    for _f0, rot, s, t in candidati[:6]:
        if any(abs(r - rot) < 2 and abs(s / s0 - 1) < 0.04 for r, s0 in visti):
            continue
        visti.append((rot, s))
        par0 = [float(rot), s * conv_l * conv_b, float(t[0] * conv_b), float(t[1] * conv_b)]
        par = _rifinisci(vic_larga, pf, par0, [0.5, par0[1] * 0.01, 4.0, 4.0], 3.0, 0.08)
        par = _rifinisci(vic_f, pf, par, [0.2, par[1] * 0.004, 1.5, 1.5], 1.5, 0.03)
        finale = _f(vic_f, fb, vic_fl, pf, par)
        if migliore is None or finale > migliore[0]:
            migliore = (finale, par)
    if migliore is None:
        return None
    finale, par = migliore

    # --- ultimo ritocco a risoluzione piena (mezzo pixel della ricerca fine) -----------
    hb2, kfb2 = _riduci(mb, _LATO_PIENO)
    hl2, kfl2 = _riduci(ml, _LATO_PIENO)
    vic_p = _vicinanza(hb2, 1)
    pp = _punti(hl2, 9000, seme=13)
    cb, cl = kfb / kfb2, kfl2 / kfl
    par2 = [par[0], par[1] * cl * cb, par[2] * cb, par[3] * cb]
    par2 = _rifinisci(vic_p, pp, par2, [0.1, par2[1] * 0.002, 1.0, 1.0], 0.5, 0.01)
    rot, sc, tx, ty = par2
    fb, kfb, fl, kfl = hb2, kfb2, hl2, kfl2

    # --- due punti lontani sui muri del livello, in % su entrambe le immagini --------
    ys, xs = np.nonzero(fl)
    punti = []
    for perc in (10, 90):
        p = np.array([[np.percentile(xs, perc), np.percentile(ys, perc)]], np.float32)
        q = porta(p, (rot, sc, tx, ty))
        punti.append([
            round(float(p[0, 0]) * kfl / wl0 * 100, 2),
            round(float(p[0, 1]) * kfl / hl0 * 100, 2),
            round(float(q[0, 0]) * kfb / wb0 * 100, 2),
            round(float(q[0, 1]) * kfb / hb0 * 100, 2),
        ])
    return EsitoAllineamento(punti=punti, punteggio=round(finale, 3), rotazione=round(rot % 360, 1),
                             scala=round(float(sc * kfb / kfl), 4))
