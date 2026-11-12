/* Bozza dei moduli: i dati inseriti non si perdono se l'invio torna con un errore.
 * All'invio di un form POST (pagina intera, non HTMX) salva i campi in sessionStorage
 * (solo questa scheda del browser, mai sul server). Alla pagina successiva:
 * - se ci sono messaggi di errore/avviso o errori nei campi, se la pagina torna senza redirect
 *   (risposta diretta al POST = modulo respinto) oppure si torna con «Indietro»,
 *   rimette i valori nei campi dello stesso form sulla stessa pagina;
 * - se l'errore porta su un'altra pagina, la bozza resta «in sospeso» (30 minuti) e torna
 *   nei campi quando si riapre la pagina del modulo;
 * - altrimenti (salvataggio riuscito) la bozza viene buttata.
 * Mai salvati: password, file, campi nascosti, token. Esclusione: data-hub-no-bozza sul form. */
(function () {
  if (window.hubFormBozza) return;

  var KEY = 'hubFormBozza';
  var MAX_AGE_MS = 30 * 60 * 1000;
  var MAX_FIELDS = 3000;
  var SKIP_TYPES = /^(password|file|hidden|submit|button|reset|image)$/;
  var SKIP_NAMES = /(csrf|password|passwd|token|secret|^pin$|otp)/i;

  function eligible(form) {
    if (!form || form.nodeName !== 'FORM') return false;
    if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return false;
    if (form.hasAttribute('data-hub-no-bozza')) return false;
    if (form.hasAttribute('hx-post') || form.hasAttribute('hx-put') || form.hasAttribute('hx-patch') ||
        form.hasAttribute('data-hx-post') || form.hasAttribute('hx-boost')) return false;
    var target = (form.getAttribute('target') || '').toLowerCase();
    return !target || target === '_self';
  }

  function fields(form) {
    return Array.prototype.filter.call(form.elements, function (el) {
      if (!el.name || el.disabled || SKIP_NAMES.test(el.name)) return false;
      var tag = el.nodeName;
      if (tag === 'SELECT' || tag === 'TEXTAREA') return true;
      return tag === 'INPUT' && !SKIP_TYPES.test((el.type || 'text').toLowerCase());
    });
  }

  /* Identità del form: azione + campo "action" nascosto + posizione tra i gemelli. */
  function formKey(form) {
    var hidden = form.querySelector('input[type="hidden"][name="action"]');
    var base = (form.getAttribute('action') || '') + '|' + (hidden ? hidden.value : '');
    var twins = Array.prototype.filter.call(document.forms, function (f) {
      var h = f.querySelector('input[type="hidden"][name="action"]');
      return (f.getAttribute('action') || '') + '|' + (h ? h.value : '') === base;
    });
    return base + '|' + twins.indexOf(form);
  }

  function snapshot(form) {
    var seen = {};
    var values = [];
    fields(form).slice(0, MAX_FIELDS).forEach(function (el) {
      var i = seen[el.name] = (seen[el.name] === undefined ? 0 : seen[el.name] + 1);
      var type = (el.type || '').toLowerCase();
      if (type === 'checkbox' || type === 'radio') values.push({ n: el.name, i: i, c: el.checked });
      else if (el.nodeName === 'SELECT' && el.multiple) {
        values.push({ n: el.name, i: i, m: Array.prototype.filter.call(el.options, function (o) { return o.selected; })
          .map(function (o) { return o.value; }) });
      } else values.push({ n: el.name, i: i, v: el.value });
    });
    return values;
  }

  function save(form) {
    if (!eligible(form)) return;
    try {
      var values = snapshot(form);
      if (!values.some(function (x) { return x.c || (x.m && x.m.length) || (x.v && String(x.v).trim()); })) return;
      sessionStorage.setItem(KEY, JSON.stringify({
        page: location.pathname, form: formKey(form), at: Date.now(), values: values,
      }));
    } catch (e) {}
  }

  function setValue(el, item) {
    var type = (el.type || '').toLowerCase();
    if (item.c !== undefined && (type === 'checkbox' || type === 'radio')) {
      if (el.checked === item.c) return false;
      el.checked = item.c;
    } else if (item.m !== undefined && el.nodeName === 'SELECT') {
      if (el.tomselect) el.tomselect.setValue(item.m, true);
      Array.prototype.forEach.call(el.options, function (o) { o.selected = item.m.indexOf(o.value) >= 0; });
    } else if (item.v !== undefined) {
      if (el.value === item.v) return false;
      if (el.tomselect) el.tomselect.setValue(item.v, true);
      else if (el._flatpickr) el._flatpickr.setDate(item.v, false);
      el.value = item.v;
    } else return false;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }

  function restore(draft) {
    var form = Array.prototype.filter.call(document.forms, eligible)
      .filter(function (f) { return formKey(f) === draft.form; })[0];
    if (!form) return 0;
    var byName = {};
    fields(form).forEach(function (el) { (byName[el.name] = byName[el.name] || []).push(el); });
    var changed = 0;
    draft.values.forEach(function (item) {
      var el = (byName[item.n] || [])[item.i];
      if (el && setValue(el, item)) changed += 1;
    });
    return changed;
  }

  function cameBack() {
    try {
      var nav = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
      return !!nav && nav.type === 'back_forward';
    } catch (e) { return false; }
  }

  /* Riquadri d'errore: quelli standard più quelli dei moduli (ticket, assets, ...).
   * Nuove pagine: basta data-hub-form-error sul riquadro dell'errore. */
  var ERROR_SELECTOR =
    '[data-hub-flash-stack] .hub-flash-error, [data-hub-flash-stack] .hub-flash-warning, ' +
    '.errorlist, .field-error, .form-errors, .is-invalid, [data-hub-form-error], ' +
    '.tkt-error, .wof-alert, .wof-error, .assets-message-error, .alert-danger, .alert-error, ' +
    '.pc-form-errors, .hub-err, .sec-error, .fm-err, .plx-errors';

  function hasErrors() {
    var nodes = document.querySelectorAll(ERROR_SELECTOR);
    for (var i = 0; i < nodes.length; i += 1) {
      if ((nodes[i].textContent || '').trim()) return true;
    }
    return false;
  }

  function hasSuccess() {
    return !!document.querySelector('[data-hub-flash-stack] .hub-flash-success');
  }

  function navEntry() {
    try { return performance.getEntriesByType && performance.getEntriesByType('navigation')[0]; }
    catch (e) { return null; }
  }

  /* Pagine d'errore (403 ecc.): la bozza resta per il ritorno con «Indietro». */
  function isErrorPage() {
    return !!document.querySelector('[data-hub-error-page]');
  }

  function drop() { try { sessionStorage.removeItem(KEY); } catch (e) {} }

  /* Bozza «in sospeso»: l'errore ha portato su un'altra pagina (es. «carica prima il
   * documento», elenco delle impostazioni). Si rimette quando si torna sul modulo. */
  var PENDING_KEY = 'hubFormBozzaSospesa';

  function restorePending() {
    var pending;
    try { pending = JSON.parse(sessionStorage.getItem(PENDING_KEY) || 'null'); } catch (e) { return; }
    if (!pending) return;
    if (Date.now() - pending.at > MAX_AGE_MS) { try { sessionStorage.removeItem(PENDING_KEY); } catch (e) {} return; }
    if (pending.page !== location.pathname) return;
    var changed = restore(pending);
    try { sessionStorage.removeItem(PENDING_KEY); } catch (e) {}
    if (changed && window.hubFlash) {
      window.hubFlash.show([{ level: 'info', text: 'Ho rimesso nei campi i dati che avevi inserito prima dell\'errore: controlla e salva di nuovo.' }]);
    }
  }

  function onReady() {
    var draft;
    try { draft = JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch (e) { return; }
    if (!draft) { restorePending(); return; }
    if (Date.now() - draft.at > MAX_AGE_MS) { drop(); restorePending(); return; }
    if (isErrorPage()) return;
    if (draft.page !== location.pathname) {
      // Solo un errore vero (non un avviso dopo un salvataggio riuscito, che si
      // ricompilerebbe come doppione la volta dopo).
      if (document.querySelector('[data-hub-flash-stack] .hub-flash-error') && !hasSuccess()) {
        try { sessionStorage.setItem(PENDING_KEY, JSON.stringify(draft)); } catch (e) {}
      }
      drop();
      restorePending();
      return;
    }
    var errors = hasErrors();
    var back = cameBack();
    // Un salvataggio riuscito fa redirect (PRG); la stessa pagina restituita senza
    // redirect è la risposta al POST, cioè il modulo tornato indietro con un errore.
    var nav = navEntry();
    var rerendered = !!nav && nav.type !== 'back_forward' && !nav.redirectCount;
    if (!errors && hasSuccess()) { drop(); return; }
    if (!errors && !back && !rerendered) { drop(); return; }
    var changed = restore(draft);
    drop();
    if (changed && errors && window.hubFlash) {
      window.hubFlash.show([{ level: 'info', text: 'Ho rimesso nei campi i dati che avevi inserito: correggi e salva di nuovo.' }]);
    }
  }

  /* In cattura: parte prima di data-hub-confirm e dei gestori dei moduli. */
  document.addEventListener('submit', function (e) { save(e.target); }, true);

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', onReady);
  else onReady();

  window.hubFormBozza = { save: save };
})();
