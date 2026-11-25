/* Barra unica delle liste KICK-OFF (Portfolio, Le mie commesse, Da gestire).
   - [data-kel-form]: le tendine [data-kel-auto] applicano il filtro appena cambiano.
   - [data-kel-cerca]: filtra mentre scrivi le righe [data-kel-riga] (testo in minuscolo
     nell'attributo); [data-kel-gruppo] si nasconde se non ha più righe visibili;
     [data-kel-vuoto] compare quando non resta niente. Invio manda la ricerca al server (tranne con data-kel-locale).
   - Menu «···» (.kel-menu): uno aperto alla volta, clic fuori lo chiude. */
(function () {
  document.addEventListener('click', function (e) {
    document.querySelectorAll('.kel-menu[open], .kel-filtri[open]').forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute('open'); });
  });
  var form = document.querySelector('[data-kel-form]');
  if (!form) return;
  form.querySelectorAll('[data-kel-auto]').forEach(function (sel) {
    sel.addEventListener('change', function () { form.submit(); });
  });
  var q = form.querySelector('[data-kel-cerca]');
  var righe = document.querySelectorAll('[data-kel-riga]');
  if (!q || !righe.length) return;
  var gruppi = document.querySelectorAll('[data-kel-gruppo]');
  var vuoto = document.querySelector('[data-kel-vuoto]');
  function filtra() {
    var t = q.value.trim().toLowerCase(), visibili = 0;
    righe.forEach(function (r) {
      var ok = !t || r.getAttribute('data-kel-riga').indexOf(t) !== -1;
      r.hidden = !ok;
      if (ok) visibili++;
    });
    gruppi.forEach(function (g) {
      g.hidden = !!t && !g.querySelector('[data-kel-riga]:not([hidden])');
    });
    if (vuoto) vuoto.hidden = visibili > 0;
  }
  q.addEventListener('input', filtra);
  // data-kel-locale: la ricerca vale solo nella pagina (il server non la usa), Invio non ricarica.
  if (q.hasAttribute('data-kel-locale')) {
    form.addEventListener('submit', function (e) { if (document.activeElement === q) e.preventDefault(); });
  }
  if (q.value) filtra();
})();
