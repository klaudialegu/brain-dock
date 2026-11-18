// Keyboard shortcuts (ADR 0017). ⌘K or Ctrl+K: quick capture. On Home it focuses the field;
// elsewhere it opens Home with the field focused. Only when a shown module accepts notes
// (the page says so with data-capture on <body>).
(() => {
  const field = document.getElementById("quick-capture");
  if (field && new URLSearchParams(location.search).has("capture")) field.focus();
  document.addEventListener("keydown", (event) => {
    if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "k") return;
    if (event.altKey || event.shiftKey) return;
    event.preventDefault();
    if (field) {
      field.focus();
    } else if (document.body.dataset.capture) {
      location.assign("/?capture");
    }
  });
})();
