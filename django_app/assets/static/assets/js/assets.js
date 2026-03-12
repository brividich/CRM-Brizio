(function () {
  function debounce(fn, wait) {
    let timer;
    return function () {
      const args = arguments;
      const ctx = this;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(ctx, args);
      }, wait);
    };
  }

  function bindRowLinks() {
    document.querySelectorAll(".assets-row-link[data-href]").forEach(function (row) {
      row.addEventListener("click", function (event) {
        if (event.target.closest("a, button, input, select, textarea, label")) {
          return;
        }
        const href = row.getAttribute("data-href");
        if (href) {
          window.location.href = href;
        }
      });
    });
  }

  function bindFiltersSmartSubmit() {
    const form = document.getElementById("assetsFilterForm");
    if (!form) {
      return;
    }
    form.querySelectorAll("select").forEach(function (select) {
      select.addEventListener("change", function () {
        form.submit();
      });
    });
    const search = form.querySelector("#id_q");
    if (search) {
      const submitDebounced = debounce(function () {
        if (search.value.trim().length >= 2 || search.value.trim().length === 0) {
          form.submit();
        }
      }, 550);
      search.addEventListener("input", submitDebounced);
    }
  }

  function bindExcelImportSubmitState() {
    const form = document.getElementById("excelImportForm");
    const submit = document.getElementById("excelImportSubmit");
    if (!form || !submit) {
      return;
    }
    form.addEventListener("submit", function () {
      submit.disabled = true;
      submit.textContent = "Import in corso...";
    });
  }

  bindRowLinks();
  bindFiltersSmartSubmit();
  bindExcelImportSubmitState();
})();

