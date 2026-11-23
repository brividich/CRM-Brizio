/*
 * Form di caricamento allegati ticket (card allegati + pagina QR della macchina).
 *
 * Progressive enhancement: senza JS il form resta un normale multipart.
 * Con JS: anteprima dei file scelti (miniatura per le foto), rimozione del
 * singolo file, trascinamento sull'area, controllo di numero/dimensione prima
 * dell'invio e pulsante in stato "invio in corso".
 *
 * Markup atteso: [data-upload-form] (un form, oppure un blocco dentro un altro
 * pannello come «Risolvi» della gestione ticket) con uno o piu' input[type=file],
 * un contenitore [data-upload-chips], un [data-upload-status] e, se form, il submit.
 * Attributi opzionali: data-max-files, data-max-mb.
 *
 * Ctrl+V con un'immagine negli appunti (screenshot) la aggiunge ai file: nel
 * blocco dove si sta scrivendo o, fuori dai campi di testo, nel primo visibile.
 * Lo script si puo' includere piu' volte nella stessa pagina: ogni blocco parte una volta sola.
 */
(function () {
  'use strict';

  var canRebuild = (function () {
    try { return typeof DataTransfer !== 'undefined' && !!new DataTransfer().items; } catch (e) { return false; }
  })();

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1).replace('.', ',') + ' MB';
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function nomeScreenshot(f, n) {
    var d = new Date();
    var due = function (x) { return (x < 10 ? '0' : '') + x; };
    var ext = ((f.type || '').split('/')[1] || 'png').replace('jpeg', 'jpg');
    return 'screenshot-' + d.getFullYear() + due(d.getMonth() + 1) + due(d.getDate()) + '-' +
      due(d.getHours()) + due(d.getMinutes()) + due(d.getSeconds()) + (n ? '-' + (n + 1) : '') + '.' + ext;
  }

  function initForm(form) {
    if (form.__uplPronto) return;
    form.__uplPronto = true;
    var inputs = Array.prototype.slice.call(form.querySelectorAll('input[type=file]'));
    var chips = form.querySelector('[data-upload-chips]');
    var status = form.querySelector('[data-upload-status]');
    var submit = form.querySelector('button[type=submit]');
    var maxFiles = parseInt(form.getAttribute('data-max-files') || '0', 10);
    var maxBytes = parseFloat(form.getAttribute('data-max-mb') || '0') * 1024 * 1024;
    var submitLabel = submit ? submit.innerHTML : '';
    var previews = [];

    // L'input nativo diventa "required" solo lato server: col JS decidiamo noi.
    inputs.forEach(function (inp) { inp.removeAttribute('required'); });

    function allFiles() {
      var out = [];
      inputs.forEach(function (inp) {
        Array.prototype.forEach.call(inp.files || [], function (f, i) { out.push({ file: f, input: inp, index: i }); });
      });
      return out;
    }

    function removeFile(inp, index) {
      var dt = new DataTransfer();
      Array.prototype.forEach.call(inp.files, function (f, i) { if (i !== index) dt.items.add(f); });
      inp.files = dt.files;
      render();
    }

    function setStatus(msg, isError) {
      if (!status) return;
      status.textContent = msg || '';
      status.classList.toggle('is-error', !!isError);
    }

    function render() {
      previews.forEach(function (u) { URL.revokeObjectURL(u); });
      previews = [];
      var files = allFiles();
      var problems = [];
      if (chips) {
        chips.innerHTML = '';
        chips.hidden = files.length === 0;
        files.forEach(function (item) {
          var f = item.file;
          var tooBig = maxBytes && f.size > maxBytes;
          if (tooBig) problems.push(f.name + ' supera ' + form.getAttribute('data-max-mb') + ' MB');
          var chip = el('li', 'upl-chip' + (tooBig ? ' is-error' : ''));
          if (/^image\//.test(f.type)) {
            var url = URL.createObjectURL(f);
            previews.push(url);
            var img = el('img', 'upl-thumb');
            img.src = url;
            img.alt = '';
            chip.appendChild(img);
          } else {
            var ext = (f.name.split('.').pop() || 'file').slice(0, 4).toUpperCase();
            chip.appendChild(el('span', 'upl-thumb upl-thumb--doc', ext));
          }
          var meta = el('span', 'upl-meta');
          meta.appendChild(el('span', 'upl-name', f.name));
          meta.appendChild(el('span', 'upl-size', tooBig ? 'Troppo grande · ' + formatSize(f.size) : formatSize(f.size)));
          chip.appendChild(meta);
          if (canRebuild) {
            var rm = el('button', 'upl-remove', '×');
            rm.type = 'button';
            rm.setAttribute('aria-label', 'Rimuovi ' + f.name);
            rm.addEventListener('click', function () { removeFile(item.input, item.index); });
            chip.appendChild(rm);
          }
          chips.appendChild(chip);
        });
      }
      if (maxFiles && files.length > maxFiles) problems.push('Massimo ' + maxFiles + ' file per invio');
      if (problems.length) {
        setStatus(problems.join(' · '), true);
      } else if (files.length) {
        setStatus(files.length === 1 ? '1 file pronto' : files.length + ' file pronti', false);
      } else {
        setStatus('', false);
      }
      if (submit) submit.disabled = files.length === 0 || problems.length > 0;
      form.classList.toggle('has-files', files.length > 0);
    }

    inputs.forEach(function (inp) { inp.addEventListener('change', render); });

    // File aggiunti a quelli gia' scelti (screenshot incollati).
    form.__uplAggiungi = function (nuovi) {
      var inp = inputs[0];
      if (!inp || !canRebuild || !nuovi.length) return false;
      var dt = new DataTransfer();
      Array.prototype.forEach.call(inp.files || [], function (f) { dt.items.add(f); });
      nuovi.forEach(function (f) { dt.items.add(f); });
      inp.files = dt.files;
      render();
      return true;
    };

    Array.prototype.forEach.call(form.querySelectorAll('[data-upload-drop]'), function (zone) {
      ['dragenter', 'dragover'].forEach(function (ev) {
        zone.addEventListener(ev, function () { zone.classList.add('is-over'); });
      });
      ['dragleave', 'drop'].forEach(function (ev) {
        zone.addEventListener(ev, function () { zone.classList.remove('is-over'); });
      });
    });

    if (form.tagName === 'FORM') form.addEventListener('submit', function (ev) {
      if (!allFiles().length) {
        ev.preventDefault();
        setStatus('Scegli almeno un file da allegare.', true);
        return;
      }
      if (submit) {
        submit.disabled = true;
        submit.classList.add('is-loading');
        submit.innerHTML = '<span class="upl-spinner" aria-hidden="true"></span> Invio in corso…';
      }
    });

    // Ritorno con "indietro" del browser: il form non deve restare bloccato.
    window.addEventListener('pageshow', function () {
      if (submit) { submit.classList.remove('is-loading'); submit.innerHTML = submitLabel; }
      render();
    });

    render();
  }

  function visibile(n) { return !!(n.offsetWidth || n.offsetHeight || n.getClientRects().length); }

  function onPaste(ev) {
    var dati = ev.clipboardData;
    if (!dati || !dati.items) return;
    var immagini = [];
    Array.prototype.forEach.call(dati.items, function (it) {
      if (it.kind === 'file' && /^image\//.test(it.type)) {
        var f = it.getAsFile();
        if (f) immagini.push(new File([f], nomeScreenshot(f, immagini.length), { type: f.type, lastModified: Date.now() }));
      }
    });
    if (!immagini.length) return;
    var dentro = ev.target && ev.target.closest ? ev.target.closest('[data-upload-form]') : null;
    var bersaglio = dentro;
    if (!bersaglio) {
      var t = ev.target;
      var scrivibile = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
      // In un campo di testo fuori dal blocco va solo se il campo e' nello stesso pannello.
      var pannello = scrivibile && t.closest ? t.closest('[data-upload-scope]') : null;
      if (pannello) bersaglio = pannello.querySelector('[data-upload-form]');
      else if (!scrivibile) {
        bersaglio = Array.prototype.filter.call(document.querySelectorAll('[data-upload-form]'), visibile)[0] || null;
      }
    }
    if (bersaglio && bersaglio.__uplAggiungi && bersaglio.__uplAggiungi(immagini)) ev.preventDefault();
  }

  function boot() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-upload-form]'), initForm);
    if (!window.__uplPaste) {
      window.__uplPaste = true;
      document.addEventListener('paste', onPaste);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
