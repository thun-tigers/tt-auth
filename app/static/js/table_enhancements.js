(function () {
    function normalize(value) {
        return (value || "").replace(/\s+/g, " ").trim();
    }

    function toQuery(value) {
        return normalize(value).toLowerCase();
    }

    function isActionLabel(label) {
        return ["aktion", "aktionen", "action", "actions"].includes(label);
    }

    function buildFilterPlaceholder(headerText) {
        const label = normalize(headerText).replace(/[▲▼]/g, "").trim();
        if (!label) {
            return "Filtern";
        }
        return label + " filtern...";
    }

    function toSortableValue(text) {
        const cleaned = normalize(text).replace(/\./g, "").replace(",", ".");
        const number = Number(cleaned.replace(/[^0-9\-+.]/g, ""));
        if (!Number.isNaN(number) && cleaned.match(/[0-9]/)) {
            return number;
        }
        return normalize(text).toLowerCase();
    }

    function getCellText(row, columnIndex) {
        const cell = row.cells[columnIndex];
        return normalize(cell ? cell.textContent : "").toLowerCase();
    }

    function getRowPairs(tbody) {
        const editRowsByKey = new Map();
        Array.from(tbody.querySelectorAll("tr.edit-row[data-key]")).forEach((row) => {
            editRowsByKey.set(row.dataset.key, row);
        });

        return Array.from(tbody.querySelectorAll("tr:not(.edit-row)")).map((row, index) => {
            if (!row.dataset.originalIndex) {
                row.dataset.originalIndex = String(index);
            }
            const key = row.dataset.key;
            const editRow = key ? editRowsByKey.get(key) : null;
            return { row, editRow };
        });
    }

    function buildSearchPlaceholder(table) {
        const customPlaceholder = table.dataset.tableSearchPlaceholder;
        if (customPlaceholder) {
            return customPlaceholder;
        }
        const title = normalize(document.title).replace(/\s*[-–|].*$/, "");
        if (title) {
            return title + " durchsuchen...";
        }
        return "In Tabelle suchen...";
    }

    function createSearchBar(table, state, applyVisibility) {
        if (table.dataset.tableSearch === "off") {
            return null;
        }

        const host = table.parentElement;
        if (!host) {
            return null;
        }

        const bar = document.createElement("div");
        bar.className = "mb-3 flex items-center justify-end";

        const inputWrap = document.createElement("div");
        inputWrap.className = "relative w-full sm:max-w-md";

        const input = document.createElement("input");
        input.type = "search";
        input.value = state.search;
        input.placeholder = buildSearchPlaceholder(table);
        input.className = "w-full h-10 rounded-xl border border-slate-300 bg-white px-4 pr-10 text-sm text-slate-900 shadow-sm outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100";

        const clearButton = document.createElement("button");
        clearButton.type = "button";
        clearButton.className = "absolute right-2 top-1/2 hidden -translate-y-1/2 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-700 dark:hover:text-slate-200";
        clearButton.setAttribute("aria-label", "Suche zurücksetzen");
        clearButton.innerHTML = '<i class="bi bi-x-lg"></i>';

        inputWrap.appendChild(input);
        inputWrap.appendChild(clearButton);
        bar.appendChild(inputWrap);
        if (host.parentElement) {
            host.parentElement.insertBefore(bar, host);
        } else {
            host.insertBefore(bar, table);
        }

        function syncClearButton() {
            clearButton.classList.toggle("hidden", !input.value);
        }

        input.addEventListener("input", () => {
            state.search = toQuery(input.value);
            syncClearButton();
            applyVisibility();
        });

        clearButton.addEventListener("click", () => {
            input.value = "";
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.focus();
        });

        syncClearButton();
        return bar;
    }

    function addColumnFilters(table, tbody, state, applyVisibility) {
        if (table.dataset.tableFilter === "off") {
            return;
        }

        const thead = table.querySelector("thead");
        const headerRow = thead ? thead.querySelector("tr") : null;
        if (!thead || !headerRow) {
            return;
        }

        const headerCells = Array.from(headerRow.querySelectorAll("th"));

        headerCells.forEach((th, index) => {
            const rawLabel = normalize(th.textContent).replace(/[▲▼]/g, "").trim();
            const label = rawLabel.toLowerCase();
            const filterable = th.dataset.filter !== "off" && label && !isActionLabel(label);

            if (!filterable || th.dataset.filterInit === "1") {
                return;
            }
            th.dataset.filterInit = "1";
            th.classList.add("relative", "whitespace-nowrap");

            const firstTextNode = Array.from(th.childNodes).find((node) => node.nodeType === Node.TEXT_NODE && normalize(node.textContent));
            if (firstTextNode) {
                firstTextNode.textContent = "";
            }

            const labelSpan = document.createElement("span");
            labelSpan.textContent = rawLabel;
            th.insertBefore(labelSpan, th.firstChild);

            const actionWrap = document.createElement("span");
            actionWrap.className = "ml-2 inline-flex items-center gap-1 align-middle shrink-0";

            const filterToggle = document.createElement("button");
            filterToggle.type = "button";
            filterToggle.className = "table-filter-button inline-flex h-6 w-6 items-center justify-center rounded text-slate-500 hover:text-indigo-600 hover:bg-slate-200/60 dark:hover:bg-slate-600/60";
            filterToggle.setAttribute("aria-label", "Filter einblenden");
            filterToggle.innerHTML = '<i class="bi bi-funnel"></i>';
            actionWrap.appendChild(filterToggle);

            const filterPanel = document.createElement("div");
            filterPanel.className = "hidden absolute left-0 top-full z-30 mt-2 min-w-[14rem]";

            const inputWrap = document.createElement("div");
            inputWrap.className = "relative";

            const input = document.createElement("input");
            input.type = "search";
            input.placeholder = buildFilterPlaceholder(rawLabel);
            input.className = "w-full px-2.5 py-1.5 pr-8 border border-slate-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-900 text-xs font-normal";

            const clearButton = document.createElement("button");
            clearButton.type = "button";
            clearButton.className = "hidden absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200";
            clearButton.setAttribute("aria-label", "Filter zuruecksetzen");
            clearButton.innerHTML = '<i class="bi bi-x-lg"></i>';

            inputWrap.appendChild(input);
            inputWrap.appendChild(clearButton);
            filterPanel.appendChild(inputWrap);
            th.appendChild(filterPanel);
            th.appendChild(actionWrap);

            filterToggle.addEventListener("click", (event) => {
                event.stopPropagation();
                const willShow = filterPanel.classList.contains("hidden");
                filterPanel.classList.toggle("hidden", !willShow);
                if (willShow) {
                    input.focus();
                }
            });

            input.addEventListener("input", () => {
                state.columnFilters.set(index, toQuery(input.value));
                clearButton.classList.toggle("hidden", !input.value);
                applyVisibility();
            });

            clearButton.addEventListener("click", () => {
                input.value = "";
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.focus();
            });
        });
    }

    function addSorting(table, tbody) {
        if (table.dataset.tableSort === "off") {
            return;
        }

        const headerRow = table.querySelector("thead tr");
        const headerCells = headerRow ? Array.from(headerRow.querySelectorAll("th")) : [];
        if (!headerCells.length) {
            return;
        }

        const collator = new Intl.Collator("de", { numeric: true, sensitivity: "base" });
        let activeIndex = -1;
        let activeDirection = "none";

        function clearIndicators() {
            headerCells.forEach((th) => {
                const indicator = th.querySelector(".table-sort-indicator");
                if (indicator) {
                    indicator.textContent = "";
                }
            });
        }

        function updateSortButtons() {
            headerCells.forEach((th, index) => {
                const button = th.querySelector(".table-sort-button");
                const icon = button ? button.querySelector("i") : null;
                if (!button || !icon) {
                    return;
                }

                button.classList.remove("text-indigo-600", "dark:text-indigo-300");
                icon.className = "bi bi-arrow-down-up";

                if (index === activeIndex && activeDirection === "asc") {
                    button.classList.add("text-indigo-600", "dark:text-indigo-300");
                    icon.className = "bi bi-sort-up";
                }
                if (index === activeIndex && activeDirection === "desc") {
                    button.classList.add("text-indigo-600", "dark:text-indigo-300");
                    icon.className = "bi bi-sort-down";
                }
            });
        }

        headerCells.forEach((th, index) => {
            const label = normalize(th.textContent).toLowerCase();
            if (th.dataset.sort === "off" || !label || isActionLabel(label) || th.dataset.sortInit === "1") {
                return;
            }
            th.dataset.sortInit = "1";

            const actionWrap = th.querySelector(".inline-flex.items-center.gap-1.align-middle") || (() => {
                const wrap = document.createElement("span");
                wrap.className = "ml-2 inline-flex items-center gap-1 align-middle";
                th.appendChild(wrap);
                return wrap;
            })();

            const sortButton = document.createElement("button");
            sortButton.type = "button";
            sortButton.className = "table-sort-button inline-flex h-6 w-6 items-center justify-center rounded text-slate-500 hover:text-indigo-600 hover:bg-slate-200/60 dark:hover:bg-slate-600/60";
            sortButton.setAttribute("aria-label", "Sortieren");
            sortButton.innerHTML = '<i class="bi bi-arrow-down-up"></i>';
            actionWrap.appendChild(sortButton);

            const indicator = document.createElement("span");
            indicator.className = "table-sort-indicator ml-1 text-xs opacity-70";
            th.appendChild(indicator);

            sortButton.addEventListener("click", (event) => {
                event.stopPropagation();

                if (activeIndex !== index) {
                    activeIndex = index;
                    activeDirection = "asc";
                } else if (activeDirection === "asc") {
                    activeDirection = "desc";
                } else if (activeDirection === "desc") {
                    activeDirection = "none";
                    activeIndex = -1;
                } else {
                    activeDirection = "asc";
                    activeIndex = index;
                }

                const pairs = getRowPairs(tbody).map((pair) => {
                    const raw = pair.row.cells[index] ? pair.row.cells[index].textContent : "";
                    return {
                        ...pair,
                        value: toSortableValue(raw),
                        originalIndex: Number(pair.row.dataset.originalIndex || "0"),
                    };
                });

                if (activeDirection === "none") {
                    pairs.sort((a, b) => a.originalIndex - b.originalIndex);
                } else {
                    pairs.sort((a, b) => {
                        let result = 0;
                        if (typeof a.value === "number" && typeof b.value === "number") {
                            result = a.value - b.value;
                        } else {
                            result = collator.compare(String(a.value), String(b.value));
                        }
                        if (result === 0) {
                            result = a.originalIndex - b.originalIndex;
                        }
                        return activeDirection === "asc" ? result : -result;
                    });
                }

                pairs.forEach((pair) => {
                    tbody.appendChild(pair.row);
                    if (pair.editRow) {
                        tbody.appendChild(pair.editRow);
                    }
                });

                clearIndicators();
                indicator.textContent = activeDirection === "asc" ? "▲" : (activeDirection === "desc" ? "▼" : "");
                updateSortButtons();
            });
        });

        updateSortButtons();
    }

    function initSmartTable(table) {
        const tbody = table.querySelector("tbody");
        if (!tbody) {
            return;
        }

        const state = {
            search: "",
            columnFilters: new Map(),
        };

        function applyVisibility() {
            const activeFilters = Array.from(state.columnFilters.entries()).filter(([, value]) => Boolean(value));
            const searchQuery = state.search;
            const pairs = getRowPairs(tbody);

            pairs.forEach(({ row, editRow }) => {
                const rowText = toQuery(row.textContent);
                const matchesSearch = !searchQuery || rowText.includes(searchQuery);
                const matchesColumns = activeFilters.every(([columnIndex, query]) => getCellText(row, columnIndex).includes(query));
                const visible = matchesSearch && matchesColumns;

                row.style.display = visible ? "" : "none";

                if (editRow) {
                    editRow.style.display = visible ? "" : "none";
                    editRow.classList.toggle("hidden", !visible);
                }
            });
        }

        createSearchBar(table, state, applyVisibility);
        addColumnFilters(table, tbody, state, applyVisibility);
        addSorting(table, tbody);
        applyVisibility();
    }

    function init() {
        Array.from(document.querySelectorAll("table.js-smart-table")).forEach(initSmartTable);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
