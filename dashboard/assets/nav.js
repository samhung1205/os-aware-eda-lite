/* Section navigation. On narrow screens the nav collapses behind a button that names the
 * current section; on wider screens the button is hidden and the nav is a plain tab row. */
(function () {
  "use strict";
  const bar = document.querySelector(".topbar");
  const btn = document.querySelector(".nav-toggle");
  const nav = document.getElementById("site-nav");
  if (!bar || !btn || !nav) return;
  const label = btn.querySelector(".nav-current");

  function sync() {
    const cur = nav.querySelector('a[aria-current="page"]');
    if (label && cur) label.textContent = cur.firstChild.textContent.trim();
  }
  function setOpen(open) {
    bar.classList.toggle("nav-open", open);
    btn.setAttribute("aria-expanded", String(open));
  }
  btn.addEventListener("click", () => setOpen(btn.getAttribute("aria-expanded") !== "true"));
  nav.addEventListener("click", (e) => { if (e.target.closest("a")) setOpen(false); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && bar.classList.contains("nav-open")) { setOpen(false); btn.focus(); }
  });
  document.addEventListener("click", (e) => { if (!bar.contains(e.target)) setOpen(false); });
  new MutationObserver(sync).observe(nav, { subtree: true, attributes: true, attributeFilter: ["aria-current"] });
  sync();
})();
