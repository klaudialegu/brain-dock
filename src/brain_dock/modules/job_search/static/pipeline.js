// Draws the pipeline Sankey from the JSON block the server rendered (no inline scripts: CSP).
(() => {
  const el = document.getElementById("pipeline-chart");
  const dataEl = document.getElementById("pipeline-data");
  if (!el || !dataEl || !window.echarts) return;

  const data = JSON.parse(dataEl.textContent);
  const dark = window.matchMedia("(prefers-color-scheme: dark)");
  let chart;

  function render() {
    const isDark = dark.matches;
    if (chart) chart.dispose();
    chart = window.echarts.init(el);
    chart.setOption({
      animation: false,
      // richText tooltips are drawn on the canvas, so no inline style attributes (CSP).
      tooltip: { trigger: "item", renderMode: "richText" },
      series: [
        {
          type: "sankey",
          nodeAlign: "left",
          left: 8,
          right: 110,
          emphasis: { focus: "adjacency" },
          data: data.nodes.map((n) => ({
            name: n.name,
            itemStyle: { color: isDark ? n.darkColor : n.color },
          })),
          links: data.links,
          lineStyle: { color: "gradient", opacity: 0.35 },
          label: { color: isDark ? "#e8e6e3" : "#1f2328" },
        },
      ],
    });
  }

  render();
  dark.addEventListener("change", render);
  window.addEventListener("resize", () => chart && chart.resize());
})();
