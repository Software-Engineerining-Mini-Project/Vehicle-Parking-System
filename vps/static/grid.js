// Live slot grid: polls /api/slots every 500 ms so a status change shows within 1 s (REQ-SLOT-01).
(function () {
    "use strict";

    var SHORT = { TWO_WHEELER: "2W", CAR: "Car", ACCESSIBLE: "Acc", EV: "EV" };
    var panels = document.querySelectorAll("[data-slot-panel]");
    if (!panels.length) {
        return;
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        if (text !== undefined) {
            node.textContent = text;
        }
        return node;
    }

    function renderCounts(box, counts) {
        var table = el("table");
        var head = el("tr");
        ["Category", "Vacant", "Total"].forEach(function (h) { head.appendChild(el("th", "", h)); });
        table.appendChild(head);
        Object.keys(counts).forEach(function (key) {
            var row = el("tr");
            row.appendChild(el("td", "", counts[key].label));
            row.appendChild(el("td", counts[key].vacant ? "" : "full", String(counts[key].vacant)));
            row.appendChild(el("td", "", String(counts[key].total)));
            table.appendChild(row);
        });
        box.replaceChildren(table);
    }

    function renderGrid(box, grid, highlight) {
        box.style.gridTemplateColumns = "repeat(" + grid[0].length + ", 1fr)";
        var cells = [];
        grid.forEach(function (row) {
            row.forEach(function (cell) {
                var node;
                if (cell.type === "SLOT") {
                    node = el("div", "cell slot " + cell.status);
                    if (cell.slot_id === highlight) {
                        node.className += " assigned";
                    }
                    node.appendChild(el("strong", "", cell.slot_id));
                    node.appendChild(el("small", "", SHORT[cell.category]));
                    node.title = cell.slot_id + " - " + cell.category + " - " + cell.status;
                } else {
                    node = el("div", "cell " + cell.type,
                              cell.type === "ENTRANCE" ? "IN" : cell.type === "EXIT" ? "OUT" : "");
                }
                cells.push(node);
            });
        });
        box.replaceChildren.apply(box, cells);
    }

    function refresh(panel) {
        fetch(panel.dataset.url, { cache: "no-store", credentials: "same-origin" })
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (data) {
                if (!data) {
                    return;
                }
                renderCounts(panel.querySelector("[data-counts]"), data.counts);
                renderGrid(panel.querySelector("[data-grid]"), data.grid, panel.dataset.highlight);
            })
            .catch(function () { /* keep the last good view if a request fails */ });
    }

    panels.forEach(function (panel) {
        refresh(panel);
        setInterval(function () { refresh(panel); }, 500);
    });
}());
