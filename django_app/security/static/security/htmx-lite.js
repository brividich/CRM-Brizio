(function () {
  function csrfTokenFromCookie() {
    var match = document.cookie.match(/(?:^|;)\s*csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function csrfTokenForForm(form) {
    var input = form.querySelector("input[name='csrfmiddlewaretoken']");
    return input ? input.value : csrfTokenFromCookie();
  }

  function submitControls(form) {
    return Array.prototype.slice.call(form.querySelectorAll("button[type='submit'], input[type='submit']"));
  }

  function applySwap(target, html, swap) {
    if (!target || swap === "none") {
      return;
    }
    if (swap === "outerHTML") {
      target.outerHTML = html;
      return;
    }
    if (swap === "beforeend") {
      target.insertAdjacentHTML("beforeend", html);
      return;
    }
    if (swap === "afterbegin") {
      target.insertAdjacentHTML("afterbegin", html);
      return;
    }
    target.innerHTML = html;
  }

  function submitHtmxForm(form) {
    var targetSelector = form.getAttribute("hx-target");
    var target = targetSelector ? document.querySelector(targetSelector) : null;
    var method = (form.getAttribute("hx-post") ? "POST" : form.method || "GET").toUpperCase();
    var url = form.getAttribute("hx-post") || form.action;
    var body = new FormData(form);
    var swap = form.getAttribute("hx-swap") || "innerHTML";
    var buttons = submitControls(form);

    if (form.dataset.hxLiteSubmitting === "true") {
      return;
    }
    form.dataset.hxLiteSubmitting = "true";
    buttons.forEach(function (button) {
      button.dataset.hxLiteDisabled = button.disabled ? "true" : "false";
      button.disabled = true;
    });

    fetch(url, {
      method: method,
      body: body,
      headers: {
        "HX-Request": "true",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrfTokenForForm(form)
      },
      credentials: "same-origin"
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.text();
      })
      .then(function (html) {
        applySwap(target, html, swap);
      })
      .catch(function () {
        if (target) {
          target.innerHTML = '<span class="sec-badge critical">Request failed</span>';
        }
      })
      .finally(function () {
        form.dataset.hxLiteSubmitting = "false";
        buttons.forEach(function (button) {
          button.disabled = button.dataset.hxLiteDisabled === "true";
          delete button.dataset.hxLiteDisabled;
        });
      });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.matches("form[hx-post]")) {
      return;
    }
    event.preventDefault();
    submitHtmxForm(form);
  });
})();
