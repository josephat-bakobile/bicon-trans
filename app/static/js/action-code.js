// Single-button forms (delete / toggle) never show a confirmation-code field on the
// page itself; the code is collected via prompt() at submit time and never touches
// the page's HTML/JS source. The server is the only place it is ever checked.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form.action-code-form").forEach((form) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();

      const confirmMsg = form.dataset.confirm;
      if (confirmMsg && !window.confirm(confirmMsg)) {
        return;
      }

      const code = window.prompt("Weka Msimbo wa Uthibitisho kuendelea:");
      if (!code) {
        return;
      }

      let hidden = form.querySelector('input[name="action_code"]');
      if (!hidden) {
        hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = "action_code";
        form.appendChild(hidden);
      }
      hidden.value = code;
      form.submit();
    });
  });
});
