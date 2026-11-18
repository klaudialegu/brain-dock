// Keyboard shortcuts (ADR 0017). ⌘K or Ctrl+K: quick capture. On Home it focuses the field;
// elsewhere it opens Home with the field focused. Only when a module accepts notes.
(() => {
  const field = document.getElementById("quick-capture");
  if (field && new URLSearchParams(location.search).has("capture")) field.focus();
  document.addEventListener("keydown", (event) => {
    if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "k") return;
    if (event.altKey || event.shiftKey) return;
    event.preventDefault();
    if (field) {
      field.focus();
    } else if (document.querySelector('nav.rail a[href^="/scratchpad"]')) {
      location.assign("/?capture");
    }
  });
})();
