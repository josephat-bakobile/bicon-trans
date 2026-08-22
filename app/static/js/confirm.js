document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form.confirm-form").forEach((form) => {
    form.addEventListener("submit", (e) => {
      const confirmMsg = form.dataset.confirm;
      if (confirmMsg && !window.confirm(confirmMsg)) {
        e.preventDefault();
      }
    });
  });
});
