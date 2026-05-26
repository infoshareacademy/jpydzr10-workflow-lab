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

    /* Flatpickr auto-init dla pol z klasa .flatpickr / input[type=date]. */
    document.addEventListener("DOMContentLoaded", function () {
        if (window.flatpickr) {
            if (window.flatpickr.l10ns && window.flatpickr.l10ns.pl) {
                window.flatpickr.localize(window.flatpickr.l10ns.pl);
            }
            document.querySelectorAll(".flatpickr, input[type='date']").forEach((el) => {
                window.flatpickr(el, {
                    dateFormat: "Y-m-d",
                    altInput: true,
                    altFormat: "d.m.Y",
                    allowInput: true,
                });
            });
        }
    });

    document.addEventListener("htmx:afterSwap", function (e) {
        if (window.flatpickr) {
            e.target.querySelectorAll(".flatpickr, input[type='date']").forEach((el) => {
                if (!el._flatpickr) {
                    window.flatpickr(el, {
                        dateFormat: "Y-m-d",
                        altInput: true,
                        altFormat: "d.m.Y",
                        allowInput: true,
                    });
                }
            });
        }
    });
})();
