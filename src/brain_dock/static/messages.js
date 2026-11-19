// The message bar (ADR 0018): × and Esc close it in place. Esc inside a text field only
// leaves the field (what was typed stays), so getting out of a field never also throws
// away an Undo: a second Esc closes the bar. Without scripts, × reloads the page, and the
// message doesn't come back.
(() => {
  const TYPING = "input, textarea, select, [contenteditable='true']";

  function close(bar) {
    const hadFocus = bar.contains(document.activeElement);
    bar.remove();
    if (hadFocus) {
      const main = document.querySelector("main");
      if (main) {
        main.setAttribute("tabindex", "-1");
        main.focus();
      }
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-message-close]");
    if (!button) return;
    event.preventDefault();
    close(button.closest("[data-message]"));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    const active = document.activeElement;
    const bar = document.querySelector("[data-message]");
    if (active && active.matches(TYPING)) {
      if (bar || active.id === "quick-capture") active.blur();
      return;
    }
    if (bar) close(bar);
  });
})();
