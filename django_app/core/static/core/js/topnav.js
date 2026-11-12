/* NOVICROM HUB — barra in alto: menu a tendina, preferiti, ricerca.
 * Spostato da template inline (12/11/2026): caricato nello stesso punto e senza defer,
 * quindi si esegue come prima; il browser lo tiene in cache. */
(function(){
  var nav = document.getElementById('topnav');
  var btn = document.getElementById('nav-toggle');
  var panel = document.getElementById('nav-links-panel');
  var more = document.getElementById('nav-more');
  if (!nav || !btn || !panel) return;

  var mqMobile = window.matchMedia('(max-width: 1100px)');

  /* ── Menu a tendina (categorie, «Altro», menu utente) ─────────────── */
  function menuOf(host) { return host.querySelector('.nav-dropdown-menu, .nav-user-panel'); }
  function toggleBtnOf(host) { return host.querySelector('.nav-dropdown-btn, .nav-user'); }
  function items(host) {
    var m = menuOf(host);
    return m ? Array.prototype.slice.call(m.querySelectorAll('a[role="menuitem"], button[role="menuitem"]')) : [];
  }
  function closeAll(except) {
    nav.querySelectorAll('.nav-dropdown.open, .nav-user-menu.open').forEach(function(el){
      if (el === except) return;
      el.classList.remove('open');
      var b = toggleBtnOf(el);
      if (b) b.setAttribute('aria-expanded', 'false');
    });
  }
  function openHost(host, focusFirst) {
    closeAll(host);
    host.classList.add('open');
    toggleBtnOf(host).setAttribute('aria-expanded', 'true');
    /* Una tendina larga (colonne) vicino al bordo destro si apre verso sinistra. */
    var m = menuOf(host);
    if (m && !mqMobile.matches) {
      m.classList.remove('nav-menu-flip', 'nav-menu-center');
      if (m.getBoundingClientRect().right > window.innerWidth - 8) m.classList.add('nav-menu-flip');
      /* Troppo larga anche girata: si centra sullo schermo, così non esce mai. */
      if (m.getBoundingClientRect().left < 8) { m.classList.remove('nav-menu-flip'); m.classList.add('nav-menu-center'); }
    }
    if (focusFirst) { var it = items(host); if (it.length) it[0].focus(); }
  }
  function closeHost(host, restoreFocus) {
    host.classList.remove('open');
    var b = toggleBtnOf(host);
    b.setAttribute('aria-expanded', 'false');
    if (restoreFocus) b.focus();
  }

  nav.addEventListener('click', function(e){
    if (e.target.closest('button[role="menuitem"]')) { closeAll(null); return; }
    var b = e.target.closest('.nav-dropdown-btn, .nav-user');
    if (!b) return;
    e.stopPropagation();
    var host = b.closest('.nav-dropdown, .nav-user-menu');
    if (host.classList.contains('open')) closeHost(host, false); else openHost(host, false);
  });

  nav.addEventListener('keydown', function(e){
    var host = e.target.closest('.nav-dropdown, .nav-user-menu');
    if (!host) return;
    var onToggle = e.target === toggleBtnOf(host);
    if (e.key === 'Escape') {
      if (host.classList.contains('open')) { e.preventDefault(); closeHost(host, true); }
      return;
    }
    if (onToggle && (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault(); openHost(host, true); return;
    }
    if (!onToggle && (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End')) {
      var list = items(host), i = list.indexOf(document.activeElement);
      if (i < 0) return;
      e.preventDefault();
      if (e.key === 'ArrowDown') i = (i + 1) % list.length;
      else if (e.key === 'ArrowUp') i = (i - 1 + list.length) % list.length;
      else if (e.key === 'Home') i = 0;
      else i = list.length - 1;
      list[i].focus();
    }
    if (!onToggle && e.key === 'Tab' && !mqMobile.matches) closeHost(host, false);
  });

  document.addEventListener('click', function(e){
    if (!e.target.closest('.nav-dropdown, .nav-user-menu, .nav-menu-filter')) closeAll(null);
    if (!e.target.closest('#topnav, [data-mbar-menu]') && panel.classList.contains('open')) setPanel(false);
  });

  /* ── Hamburger (≤1100px) ──────────────────────────────────────────── */
  function setPanel(open) {
    panel.classList.toggle('open', open);
    btn.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    btn.setAttribute('aria-label', open ? 'Chiudi menu' : 'Apri menu');
    if (mbarMenu) {
      mbarMenu.setAttribute('aria-expanded', open ? 'true' : 'false');
      mbarMenu.classList.toggle('is-active', open);
    }
    /* Sotto il menu aperto la pagina non scorre (sul telefono scorreva insieme). */
    document.documentElement.classList.toggle('nav-panel-lock', open && mqMobile.matches);
    if (open && mqMobile.matches) {
      if (filterInput) { filterInput.value = ''; filterMenu(''); }
      /* La categoria della pagina corrente si apre da sola. */
      var cur = panel.querySelector('.nav-dropdown.active:not(.nav-more)');
      /* Dopo il click in corso: il listener sul documento chiuderebbe subito le tendine. */
      if (cur) setTimeout(function(){
        if (!cur.classList.contains('open')) openHost(cur, false);
        cur.scrollIntoView({ block: 'start' });
      }, 0);
    }
  }

  /* ── Filtro del menu a hamburger ──────────────────────────────────── */
  var filterInput = panel.querySelector('[data-nav-filter]');
  function norm(s) { return String(s || '').toLowerCase().replace(/\s+/g, ' ').trim(); }
  function filterMenu(q) {
    q = norm(q);
    panel.querySelectorAll('[data-nav-top]').forEach(function(el){
      if (!el.classList.contains('nav-dropdown')) {
        el.classList.toggle('nav-filter-miss', !!q && norm(el.textContent).indexOf(q) === -1);
        return;
      }
      var catHit = !!q && norm(el.querySelector('.nav-dropdown-btn').textContent).indexOf(q) !== -1;
      var anyHit = false;
      el.querySelectorAll('.nav-dropdown-item').forEach(function(it){
        var hit = !q || catHit || norm(it.textContent).indexOf(q) !== -1;
        it.classList.toggle('nav-filter-miss', !hit);
        if (hit) anyHit = true;
      });
      el.querySelectorAll('.nav-dd-section').forEach(function(sec){
        sec.classList.toggle('nav-filter-miss', !!q && !sec.querySelector('.nav-dropdown-item:not(.nav-filter-miss)'));
      });
      el.classList.toggle('nav-filter-miss', !!q && !anyHit);
      /* Con un filtro attivo le categorie con risultati si aprono da sole. */
      if (q) {
        el.classList.toggle('open', anyHit);
        el.querySelector('.nav-dropdown-btn').setAttribute('aria-expanded', anyHit ? 'true' : 'false');
      } else if (!el.classList.contains('active')) {
        el.classList.remove('open');
        el.querySelector('.nav-dropdown-btn').setAttribute('aria-expanded', 'false');
      }
    });
  }
  if (filterInput) {
    filterInput.addEventListener('input', function(){ filterMenu(filterInput.value); });
    filterInput.addEventListener('keydown', function(e){
      if (e.key !== 'Enter') return;
      var first = panel.querySelector('a.nav-a:not(.nav-filter-miss):not([hidden]), .nav-dropdown.open .nav-dropdown-item:not(.nav-filter-miss)');
      if (first && norm(filterInput.value)) { e.preventDefault(); first.click(); }
    });
  }
  btn.addEventListener('click', function(){ setPanel(!panel.classList.contains('open')); });
  /* «Menu» della barra in basso (telefono): stesso pannello dell'hamburger. */
  var mbarMenu = document.querySelector('[data-mbar-menu]');
  if (mbarMenu) mbarMenu.addEventListener('click', function(){
    setPanel(!panel.classList.contains('open'));
    if (panel.classList.contains('open')) panel.scrollTop = 0;
  });
  panel.addEventListener('click', function(e){ if (e.target.closest('a')) setPanel(false); });
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape' && panel.classList.contains('open')) { setPanel(false); btn.focus(); }
  });

  /* ── Overflow «Altro»: le voci che non entrano nella barra ─────────── */
  var tops = Array.prototype.slice.call(panel.querySelectorAll('[data-nav-top]'));
  var moreMenu = more ? more.querySelector('.nav-more-menu') : null;

  function fillMore(hidden) {
    moreMenu.innerHTML = '';
    hidden.forEach(function(el){
      if (el.classList.contains('nav-dropdown')) {
        var head = document.createElement('div');
        head.className = 'nav-more-head';
        head.textContent = el.querySelector('.nav-dropdown-btn .nav-label').textContent.trim();
        moreMenu.appendChild(head);
        el.querySelectorAll('.nav-dd-head, .nav-dropdown-item').forEach(function(n){
          if (n.classList.contains('nav-dd-head')) {
            var sub = document.createElement('div');
            sub.className = 'nav-more-subhead';
            sub.textContent = n.textContent.trim();
            moreMenu.appendChild(sub);
          } else {
            moreMenu.appendChild(n.cloneNode(true));
          }
        });
      } else {
        var a = el.cloneNode(true);
        a.className = 'nav-dropdown-item' + (el.classList.contains('active') ? ' active' : '');
        a.removeAttribute('data-nav-top');
        a.setAttribute('role', 'menuitem');
        moreMenu.appendChild(a);
      }
    });
  }

  /* Prima di spostare voci in «Altro» le dimensioni scendono da sole (data-fit 0→3, stili in theme.css):
     si misura davvero, quindi vale per ogni schermo, zoom e «dimensione testo» delle preferenze. */
  var FIT_MAX = 3;
  function sfora() { return panel.scrollWidth > panel.clientWidth + 1; }
  function layout() {
    if (!more || !moreMenu) return;
    tops.forEach(function(el){ el.hidden = false; });
    more.hidden = true;
    nav.setAttribute('data-fit', '0');
    if (mqMobile.matches) return;
    for (var liv = 1; liv <= FIT_MAX && sfora(); liv++) nav.setAttribute('data-fit', String(liv));
    if (!sfora()) return;
    more.hidden = false;
    var hidden = [];
    /* Nasconde dal fondo finché tutto entra; la voce attiva resta visibile se possibile. */
    for (var i = tops.length - 1; i >= 0 && panel.scrollWidth > panel.clientWidth + 1; i--) {
      if (tops[i].classList.contains('active') && i > 0) continue;
      tops[i].hidden = true;
      hidden.unshift(tops[i]);
    }
    if (panel.scrollWidth > panel.clientWidth + 1) {
      for (var j = tops.length - 1; j >= 0 && panel.scrollWidth > panel.clientWidth + 1; j--) {
        if (!tops[j].hidden) { tops[j].hidden = true; hidden.unshift(tops[j]); }
      }
    }
    var aggiornaAltro = function(){
      hidden.sort(function(a, b){ return tops.indexOf(a) - tops.indexOf(b); });
      fillMore(hidden);
      more.classList.toggle('active', hidden.some(function(el){ return el.classList.contains('active'); }));
      more.querySelector('.nav-dropdown-btn').classList.toggle('active', more.classList.contains('active'));
    };
    aggiornaAltro();
    /* «Altro» acceso è in grassetto, quindi più largo: se ora non entra, esce un'altra voce. */
    for (var k = tops.length - 1; k >= 0 && sfora(); k--) {
      if (!tops[k].hidden) { tops[k].hidden = true; hidden.push(tops[k]); aggiornaAltro(); }
    }
  }

  var raf = 0;
  function schedule() { cancelAnimationFrame(raf); raf = requestAnimationFrame(layout); }
  window.addEventListener('resize', schedule);
  if (mqMobile.addEventListener) mqMobile.addEventListener('change', function(){ setPanel(false); schedule(); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(schedule);
  /* La zona destra puo' cambiare larghezza dopo il load (badge dal polling, ecc.). */
  var right = nav.querySelector('.nav-right');
  if (right && window.ResizeObserver) new ResizeObserver(schedule).observe(right);
  layout();

  /* ── Stelle: griglia «Moduli» e tendina «Preferiti» (stesso salvataggio della home) ── */
  var preferiti = document.getElementById('nav-preferiti');
  if (preferiti) {
    var lista = preferiti.querySelector('[data-nav-preferiti]');
    var vuoto = preferiti.querySelector('[data-nav-preferiti-vuoto]');
    var griglia = document.getElementById('nav-moduli');
    var msg = griglia ? griglia.querySelector('[data-nav-star-msg]') : null;
    var msgBase = msg ? msg.textContent : '';
    var stars = function(id){
      return Array.prototype.filter.call(nav.querySelectorAll('[data-nav-star]'), function(b){ return b.getAttribute('data-nav-star') === id; });
    };
    var segna = function(id, on){
      stars(id).forEach(function(b){
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        b.title = on ? 'Togli dai preferiti' : 'Metti nei preferiti';
      });
      var riga = Array.prototype.filter.call(lista.children, function(r){ return r.getAttribute('data-star-row') === id; })[0];
      if (!on && riga) riga.remove();
      if (on && !riga && griglia) {
        var fonte = Array.prototype.filter.call(griglia.querySelectorAll('[data-star-row]'), function(r){ return r.getAttribute('data-star-row') === id; })[0];
        if (fonte) lista.appendChild(fonte.cloneNode(true));
      }
      vuoto.hidden = lista.children.length > 0;
    };
    nav.addEventListener('click', function(e){
      var b = e.target.closest('[data-nav-star]');
      if (!b) return;
      e.preventDefault();
      e.stopPropagation();
      var id = b.getAttribute('data-nav-star');
      var on = b.getAttribute('aria-pressed') !== 'true';
      var meta = document.querySelector("meta[name='csrf-token']");
      var dati = new FormData();
      dati.append('azione', 'preferito');
      dati.append('modulo', id);
      dati.append('on', on ? '1' : '0');
      segna(id, on);
      if (msg) msg.textContent = msgBase;
      fetch(preferiti.getAttribute('data-preferito-url'), {
        method: 'POST',
        headers: { 'X-CSRFToken': meta ? meta.getAttribute('content') : '', 'X-Requested-With': 'XMLHttpRequest' },
        body: dati
      }).then(function(r){ return r.json(); }).then(function(res){
        if (res && res.ok) return;
        segna(id, !on);
        if (msg) msg.textContent = (res && res.error) || 'Preferito non salvato.';
      }).catch(function(){
        segna(id, !on);
        if (msg) msg.textContent = 'Preferito non salvato.';
      });
    });
  }

  /* ── Tema chiaro/scuro dal menu utente ────────────────────────────── */
  var themeBtn = nav.querySelector('[data-theme-toggle]');
  if (themeBtn) {
    themeBtn.addEventListener('click', function(){
      var dark = !document.body.classList.contains('theme-dark');
      document.body.classList.toggle('theme-dark', dark);
      var meta = document.querySelector("meta[name='csrf-token']");
      var body = new FormData();
      body.append('theme_mode', dark ? 'dark' : 'light');
      fetch(themeBtn.getAttribute('data-url'), {
        method: 'POST',
        headers: { 'X-CSRFToken': meta ? meta.getAttribute('content') : '', 'X-Requested-With': 'XMLHttpRequest' },
        body: body
      }).catch(function(){});
    });
  }
})();
