/* ============================================================================
 * Planer Maszyn Budowlanych — globalne komponenty Alpine.js
 * ============================================================================
 *
 * Wszystkie reuzywalne komponenty Alpine + auto-init Flatpickr trafiaja tu
 * (zamiast inline w template'ach). Aby uniknac globalnego scope leak, zostaje
 * tylko `window.XYZ` co jest wymagane przez Alpine `x-data="XYZ()"`.
 */

(function () {
    "use strict";

    /* timelineShell — sterownik widoku timeline. Hydratacja danych z json_script.

       Wave 14-A Bundle 9 -- dodane keyboard navigation arrows (left/right):
       gdy user nacisnie <- lub -> na fizycznej klawiaturze, scroll-ujemy
       timeline grid horyzontalnie o ~1 day-cell (60px). Fallback dla
       browsers ktore hide scrollbar (Comet/Perplexity). User stoi
       gdziekolwiek na stronie -- @window listener z guard na input/select. */
    window.timelineShell = function () {
        return {
            machineRows: [],
            filtersOpen: true,
            period: "week",

            init() {
                try {
                    const rowsEl = document.getElementById("machine-rows-data");
                    if (rowsEl) this.machineRows = JSON.parse(rowsEl.textContent);
                } catch (e) {
                    /* eslint-disable-next-line no-console */
                    console.warn("Timeline hydration failed", e);
                }
                window.addEventListener("refreshTimeline", () => this.reload());

                // Wave 14-A Bundle 9 — keyboard scroll arrows (left/right).
                // Guard: gdy focus jest w input/textarea/select, ignorujemy
                // (arrow keys to natywna nawigacja w form fields).
                window.addEventListener("keydown", (e) => this.handleArrowKey(e));
            },

            get totalReservations() {
                return this.machineRows.reduce((sum, m) => sum + (m.bars ? m.bars.length : 0), 0);
            },

            get totalMachines() {
                return this.machineRows.length;
            },

            openQuickReserve(machineUid, day) {
                window.dispatchEvent(new CustomEvent("open-quick-reserve", {
                    detail: { machineUid, day },
                }));
            },

            reload() {
                if (window.htmx) {
                    const grid = document.getElementById("timeline-grid");
                    if (grid) window.htmx.trigger(grid, "refreshTimeline");
                }
            },

            // Wave 14-A Bundle 9 -- horizontal scroll przez arrow keys.
            // Krok 64px (~1 day-cell wide). Smooth scroll dla lepszego UX.
            handleArrowKey(e) {
                if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
                // Guard -- nie scroll-uj gdy user pisze w polu formularza.
                const tag = (e.target && e.target.tagName) || "";
                if (["INPUT", "TEXTAREA", "SELECT"].indexOf(tag) !== -1) return;
                if (e.target && e.target.isContentEditable) return;

                const wrap = document.querySelector(".timeline-wrap");
                if (!wrap) return;
                const step = 64;
                wrap.scrollBy({
                    left: e.key === "ArrowRight" ? step : -step,
                    behavior: "smooth",
                });
                e.preventDefault();
            },
        };
    };

    /* quickReserveModal — HTMX-driven modal. */
    window.quickReserveModal = function () {
        return {
            open: false,
            machineUid: "",
            startDate: "",
            endDate: "",
            person: "",

            init() {
                window.addEventListener("open-quick-reserve", (e) => this.show(e.detail));
                window.addEventListener("keydown", (e) => {
                    if (e.key === "Escape" && this.open) this.open = false;
                });
                this.$watch("open", (val) => {
                    if (val) {
                        this.$nextTick(() => {
                            const first = this.$refs.firstFocus;
                            if (first) first.focus();
                        });
                    }
                });
            },

            show(detail) {
                this.machineUid = detail.machineUid || "";
                this.startDate = detail.day || "";
                this.endDate = detail.day || "";
                this.person = document.body.dataset.userName || "";
                this.open = true;
            },

            close() {
                this.open = false;
            },
        };
    };

    /* toast — globalny notifier (Alpine x-data) z auto-fade po 3s. */
    window.toast = function () {
        return {
            visible: false,
            kind: "success",
            message: "",
            timeoutId: null,

            init() {
                window.addEventListener("toast", (e) => this.show(e.detail));
                window.addEventListener("showToast", (e) => this.show(e.detail));
            },

            show({ kind = "success", message = "", level, duration = 3000 } = {}) {
                // Backend wysyla `level` (success/error/...), my mapujemy na `kind`.
                this.kind = level === "error" ? "error" : kind;
                this.message = message;
                this.visible = true;
                if (this.timeoutId) clearTimeout(this.timeoutId);
                this.timeoutId = setTimeout(() => { this.visible = false; }, duration);
            },
        };
    };

    /* detailTabs — tabs w machines/detail. */
    window.detailTabs = function (initial) {
        return {
            active: initial || "info",
            select(name) {
                this.active = name;
                try {
                    window.history.replaceState(null, "", "#" + name);
                } catch (e) { /* ignore */ }
            },
            init() {
                const hash = (window.location.hash || "").replace("#", "");
                if (hash) this.active = hash;
            },
        };
    };

    /* Flatpickr a11y: altInput (widoczny klon) nie dziedziczy etykiety ani
       sensownego tabindex. onReady kopiuje tekst <label for=origId> jako
       aria-label na altInput i czysci dodatni tabindex (anti-pattern WCAG).
       Oryginalny (ukryty) input zachowuje name -> formularz dziala bez zmian. */
    function flatpickrA11yReady(selectedDates, dateStr, instance) {
        var alt = instance.altInput;
        if (!alt) return;
        var ti = alt.getAttribute("tabindex");
        if (ti !== null && parseInt(ti, 10) > 0) alt.setAttribute("tabindex", "0");
        if (!alt.getAttribute("aria-label")) {
            var orig = instance.input;
            var labelText = "";
            if (orig.id) {
                var lbl = document.querySelector('label[for="' + orig.id + '"]');
                if (lbl) labelText = lbl.textContent.trim();
            }
            if (!labelText && orig.getAttribute("aria-label")) {
                labelText = orig.getAttribute("aria-label");
            }
            if (labelText) alt.setAttribute("aria-label", labelText);
        }
    }

    function buildFlatpickrConfig(extra) {
        var cfg = {
            dateFormat: "Y-m-d",
            altInput: true,
            altFormat: "d.m.Y",
            allowInput: true,
            onReady: flatpickrA11yReady,
        };
        if (extra) {
            for (var k in extra) {
                if (Object.prototype.hasOwnProperty.call(extra, k)) cfg[k] = extra[k];
            }
        }
        return cfg;
    }

    /* Flatpickr auto-init dla pol z klasa .flatpickr / input[type=date]. */
    document.addEventListener("DOMContentLoaded", function () {
        if (window.flatpickr) {
            // Lokalizuj kalendarz do polskiego TYLKO gdy interfejs jest po polsku.
            // W trybie EN zostaje wbudowany angielski flatpickr (nazwy dni/miesięcy
            // nie mieszają się z językiem UI).
            const uiLang = (document.documentElement.lang || "pl").toLowerCase();
            if (uiLang.startsWith("pl") && window.flatpickr.l10ns && window.flatpickr.l10ns.pl) {
                window.flatpickr.localize(window.flatpickr.l10ns.pl);
            }
            // data-skip-flatpickr: pozostaw natywny <input type=date> (w pelni
            // dostepny — etykieta for/id, brak altInput). Uzywane tam, gdzie liczy
            // sie deterministyczna dostepnosc (filtry raportow).
            document.querySelectorAll(".flatpickr, input[type='date']:not([data-skip-flatpickr])").forEach((el) => {
                // static: renderuj kalendarz inline w DOM modala (nie na body),
                // zeby klikniecie daty nie bylo interpretowane jako "click outside
                // modal" -> nie zamyka popupa rezerwacji.
                window.flatpickr(el, buildFlatpickrConfig({ static: true }));
            });
        }
    });

    document.addEventListener("htmx:afterSwap", function (e) {
        if (window.flatpickr) {
            e.target.querySelectorAll(".flatpickr, input[type='date']:not([data-skip-flatpickr])").forEach((el) => {
                if (!el._flatpickr) {
                    window.flatpickr(el, buildFlatpickrConfig());
                }
            });
        }
    });

    /* ========================================================================
     * Delegowane handlery zdarzeń (strict CSP — zero inline ``on*`` atrybutow).
     * ------------------------------------------------------------------------
     * Po usunieciu ``'unsafe-inline'`` ze ``script-src`` inline event-handlery
     * (``onclick``/``onchange``/``onsubmit``) sa blokowane przez przegladarke.
     * Zastepujemy je delegacja na ``document`` + atrybutami ``data-*``.
     * KLUCZOWE: listener na ``document`` przezywa podmiany HTMX (partiale listy
     * sa swapowane bez pelnego reloadu), wiec np. dialogi potwierdzenia dzialaja
     * takze PO przefiltrowaniu/stronicowaniu listy rezerwacji — inaczej niz
     * dyrektywy Alpine, ktore nie re-inicjalizuja sie na swapowanym HTML.
     * ====================================================================== */

    // 1) Potwierdzenie przed wyslaniem formularza: <form data-confirm="...">.
    //    Zdarzenie `submit` babelkuje do document, wiec lapie tez formularze
    //    wstrzykniete przez HTMX. Anulowanie w confirm() blokuje wysylke.
    document.addEventListener("submit", function (e) {
        const form = e.target;
        if (form instanceof HTMLFormElement && form.dataset.confirm) {
            if (!window.confirm(form.dataset.confirm)) {
                e.preventDefault();
            }
        }
    });

    // 2) Auto-submit selecta po zmianie: <select data-autosubmit>.
    //    Zastepuje onchange="this.form.submit()" (przelacznik jezyka, per-page).
    document.addEventListener("change", function (e) {
        const el = e.target;
        if (el && el.matches && el.matches("[data-autosubmit]")) {
            const form = el.form || (el.closest && el.closest("form"));
            if (form) form.submit();
        }
    });

    // 3) Przycisk „wstecz" z fallbackiem: <button data-history-back> (403/404).
    document.addEventListener("click", function (e) {
        const trigger = e.target.closest && e.target.closest("[data-history-back]");
        if (trigger && window.history.length > 1) {
            window.history.back();
        }
    });

    // 4) Klikalny wiersz tabeli: <tr data-row-href="URL"> (lista budow).
    //    Klikniecie w link/przycisk wewnatrz wiersza dziala normalnie (nie
    //    porywamy go) — zastepuje onclick + onclick="event.stopPropagation()".
    document.addEventListener("click", function (e) {
        if (!e.target.closest) return;
        if (e.target.closest("a, button, input, select, textarea, label")) return;
        const row = e.target.closest("[data-row-href]");
        if (row) window.location = row.dataset.rowHref;
    });
})();
