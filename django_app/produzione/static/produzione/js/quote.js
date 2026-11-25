/* Andamento quote: cambiare programma o quota ricarica la pagina (il programma azzera la quota). */
(function () {
  document.querySelectorAll('form[data-quote-filtri] select').forEach(function (sel) {
    sel.addEventListener('change', function () {
      var form = sel.form;
      if (sel.name === 'prog' && form.elements.q) form.elements.q.value = '';
      form.submit();
    });
  });
})();
