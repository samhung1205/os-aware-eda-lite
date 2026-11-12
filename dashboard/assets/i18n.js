/* Language switch (English / Traditional Chinese). English is the default and the source text.
 *   - Choice order: ?lang=zh-TW|en in the URL, then the saved choice, then English.
 *   - Scripts call I18N.L(en, zh) wherever they build text.
 *   - Static HTML marks translatable nodes with data-zh (text), data-zh-title, data-zh-aria-label
 *     and data-zh-content (meta); the English stays in the markup.
 *   - Switching saves the choice and reloads, so every view re-renders in one language.
 * Numbers never pass through here: both languages format the same values from the data bundle. */
(function () {
  "use strict";
  const KEY = "dashboard-lang";
  const ZH = "zh-TW", EN = "en";
  const norm = (v) => (v === ZH || v === "zh" ? ZH : v === EN ? EN : null);

  let lang = null;
  try { lang = norm(new URLSearchParams(location.search).get("lang")); } catch (e) { /* ignore */ }
  if (lang) { try { localStorage.setItem(KEY, lang); } catch (e) { /* private mode */ } }
  if (!lang) { try { lang = norm(localStorage.getItem(KEY)); } catch (e) { /* private mode */ } }
  lang = lang || EN;

  const zh = lang === ZH;
  document.documentElement.lang = lang;
  const L = (en, zhText) => (zh && zhText !== undefined ? zhText : en);

  function applyStatic(root) {
    if (!zh) return;
    root.querySelectorAll("[data-zh]").forEach((el) => { el.textContent = el.getAttribute("data-zh"); });
    ["title", "aria-label", "content"].forEach((attr) => {
      root.querySelectorAll(`[data-zh-${attr}]`).forEach((el) => el.setAttribute(attr, el.getAttribute(`data-zh-${attr}`)));
    });
  }

  function setLang(next) {
    try { localStorage.setItem(KEY, next); } catch (e) { /* private mode: URL still carries it */ }
    const url = new URL(location.href);
    if (next === EN) url.searchParams.delete("lang"); else url.searchParams.set("lang", next);
    location.replace(url.toString());
  }

  function addToggle() {
    const brand = document.querySelector(".brand");
    if (!brand) return;
    const b = document.createElement("button");
    b.type = "button"; b.className = "lang-toggle";
    b.lang = zh ? EN : ZH;
    b.textContent = zh ? "EN" : "中文";
    b.title = zh ? "Switch to English" : "切換為繁體中文";
    b.setAttribute("aria-label", b.title);
    b.addEventListener("click", () => setLang(zh ? EN : ZH));
    const before = brand.querySelector(".nav-toggle");
    brand.insertBefore(b, before || null);
  }

  window.I18N = { lang, zh, L, setLang };
  applyStatic(document);
  addToggle();
})();
