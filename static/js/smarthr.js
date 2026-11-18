(function () {
  "use strict";

  // Confirmation dialog for forms/buttons marked with data-confirm.
  var modalEl = document.getElementById("confirmModal");
  if (modalEl && window.bootstrap) {
    var modal = new bootstrap.Modal(modalEl);
    var pendingForm = null;
    document.addEventListener("submit", function (event) {
      var form = event.target;
      var message = form.getAttribute && form.getAttribute("data-confirm");
      if (!message || form.dataset.confirmed === "1") return;
      event.preventDefault();
      pendingForm = form;
      modalEl.querySelector("[data-confirm-message]").textContent = message;
      modal.show();
    });
    modalEl.querySelector("[data-confirm-accept]").addEventListener("click", function () {
      if (pendingForm) {
        pendingForm.dataset.confirmed = "1";
        modal.hide();
        pendingForm.submit();
      }
    });
  }

  // Prevent double submits and show a loading state.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (event.defaultPrevented || form.getAttribute("data-confirm") && form.dataset.confirmed !== "1") return;
    var btn = form.querySelector("button[type=submit].loading-btn, button.loading-btn:not([type])");
    if (btn) {
      btn.classList.add("is-loading");
      btn.setAttribute("aria-busy", "true");
    }
  });
})();
