(() => {
  const key = "card-lottery-hidden-v2";
  const read = () => {
    try { return new Set(JSON.parse(localStorage.getItem(key) || "[]")); }
    catch { return new Set(); }
  };
  const save = (hidden) => {
    try { localStorage.setItem(key, JSON.stringify([...hidden])); }
    catch { /* private browsing can disable storage; CSS hiding still works */ }
  };
  const paint = (hidden) => {
    document.querySelectorAll(".hide-toggle").forEach((toggle) => {
      toggle.checked = hidden.has(toggle.dataset.lotteryId);
    });
  };
  document.addEventListener("DOMContentLoaded", () => {
    const hidden = read();
    paint(hidden);
    document.addEventListener("change", (event) => {
      const toggle = event.target;
      if (!(toggle instanceof HTMLInputElement) || !toggle.matches(".hide-toggle")) return;
      if (toggle.checked) hidden.add(toggle.dataset.lotteryId);
      else hidden.delete(toggle.dataset.lotteryId);
      save(hidden);
    });
    document.querySelector(".reset-hidden-v2")?.addEventListener("click", (event) => {
      event.preventDefault();
      hidden.clear();
      try { localStorage.removeItem(key); } catch { /* no stored value */ }
      paint(hidden);
    });
  });
})();
