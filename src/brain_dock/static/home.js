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
      layout();
    });
  }

  // The "Add module" tile takes the width of the card right above it, so their edges line
  // up. Narrow screens stack everything full width, so the tile is left alone there.
  const wide = window.matchMedia("(min-width: 861px)");
  function alignTile() {
    const tile = grid.querySelector(".add-module");
    if (!tile) return;
    tile.style.gridColumn = "";
    if (!wide.matches) return;
    const t = tile.getBoundingClientRect();
    let above = null;
    for (const item of grid.children) {
      if (item === tile) continue;
      const r = item.getBoundingClientRect();
      const stacked = r.bottom <= t.top + 1 && Math.abs(r.left - t.left) < 4;
      if (stacked && (!above || r.bottom > above.rect.bottom)) above = { item, rect: r };
    }
    if (above && Math.abs(above.rect.width - t.width) > 1) {
      tile.style.gridColumn = getComputedStyle(above.item).gridColumnStart;
      pack();
    }
  }

  function layout() {
    pack();
    alignTile();
  }

  pack();
  alignTile();
  new ResizeObserver(soon).observe(grid);
  if (document.fonts) document.fonts.ready.then(soon);
})();
