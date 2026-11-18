// Home (ADR 0016): pack the cards so a short card leaves no gap under it. The grid gets tiny
// rows, and each card spans as many as its own height (plus the gap). Without scripts the
// grid still works: cards align to the top of each row.
(() => {
  const grid = document.querySelector(".grid[data-pack]");
  if (!grid) return;
  const ROW = 2;
  const GAP = 22;

  function pack() {
    grid.classList.add("packed");
    for (const item of grid.children) {
      item.style.gridRowEnd = "auto";
      const height = item.getBoundingClientRect().height;
      item.style.gridRowEnd = `span ${Math.ceil((height + GAP) / ROW)}`;
    }
  }

  let queued = null;
  function soon() {
    if (queued !== null) return;
    queued = requestAnimationFrame(() => {
      queued = null;
      pack();
    });
  }

  pack();
  new ResizeObserver(soon).observe(grid);
  if (document.fonts) document.fonts.ready.then(soon);
})();
