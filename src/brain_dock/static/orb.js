// The play-brief orb (ADR 0016): a small cloud of ink dots on one canvas, no libraries.
// Idle: the dots breathe slowly. Hover: they lean toward the pointer. Reduced motion: drawn
// once, still. A hidden tab stops the drawing loop. The canvas is decorative (aria-hidden);
// the button's own text is its label. Audio-driven ripples come with playback.
(() => {
  const wrap = document.querySelector("[data-orb]");
  if (!wrap) return;
  const canvas = wrap.querySelector("canvas");
  const ctx = canvas.getContext("2d");
  const still = window.matchMedia("(prefers-reduced-motion: reduce)");
  const ACROSS = 9; // dots across the diameter: few and big, so it reads as dots
  const started = performance.now();
  let pointer = null;
  let frame = null;
  let drawn = 0; // frames drawn: lets a test see the loop run without comparing pixels

  function draw(now) {
    const size = canvas.clientWidth;
    if (!size) return;
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(size * dpr)) {
      canvas.width = canvas.height = Math.round(size * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    wrap.dataset.frames = String(++drawn);
    const t = still.matches ? 0 : (now - started) / 1000;
    const center = size / 2;
    const radius = center * 0.94;
    const step = (2 * radius) / ACROSS;
    for (let i = 0; i < ACROSS; i++) {
      for (let j = 0; j < ACROSS; j++) {
        const x = center - radius + step * (i + 0.5);
        const y = center - radius + step * (j + 0.5);
        const dist = Math.hypot(x - center, y - center);
        if (dist > radius) continue;
        const k = dist / radius; // 0 in the middle, 1 at the edge
        const angle = Math.atan2(y - center, x - center);
        // A slow wave moving outward: the dots breathe.
        const breathe = still.matches ? 0 : Math.sin(t * 1.05 - k * 2.3) * step * 0.09;
        let px = x + Math.cos(angle) * breathe;
        let py = y + Math.sin(angle) * breathe;
        if (pointer && !still.matches) {
          const dx = pointer.x - px;
          const dy = pointer.y - py;
          const away = Math.hypot(dx, dy) || 1;
          const reach = radius * 0.8;
          if (away < reach) {
            const pull = (1 - away / reach) ** 2 * step * 0.9;
            px += (dx / away) * pull;
            py += (dy / away) * pull;
          }
        }
        // Bigger and darker toward the middle, smaller and lighter at the edge.
        const r = Math.max(step * 0.46 * (1 - k * 0.32), 1);
        ctx.fillStyle = `rgba(29, 27, 24, ${(1 - k * 0.45).toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(px, py, r, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  function loop(now) {
    draw(now);
    frame = requestAnimationFrame(loop);
  }
  function start() {
    if (frame === null && !still.matches && !document.hidden) {
      frame = requestAnimationFrame(loop);
    }
    wrap.dataset.animating = frame === null ? "false" : "true";
  }
  function stop() {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    wrap.dataset.animating = "false";
  }

  wrap.addEventListener("pointermove", (event) => {
    const box = canvas.getBoundingClientRect();
    pointer = { x: event.clientX - box.left, y: event.clientY - box.top };
  });
  wrap.addEventListener("pointerleave", () => {
    pointer = null;
  });
  document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
  still.addEventListener("change", () => {
    stop();
    draw(performance.now());
    start();
  });
  draw(performance.now());
  start();
})();
