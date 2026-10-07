async function load() {
  const role = document.getElementById("role").value;
  const status = document.getElementById("status");
  status.textContent = "Loading…";
  const res = await fetch("/api/reports", { headers: { "X-Role": role } });
  const tbody = document.querySelector("#reports tbody");
  tbody.innerHTML = "";
  if (!res.ok) { status.textContent = `Error ${res.status}`; return; }
  const rows = await res.json();
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.dataset.id = r.id;
    tr.innerHTML = `<td>${r.id}</td><td>${r.title}</td><td>${r.owner}</td><td>${r.rows}</td>`;
    tbody.appendChild(tr);
  }
  status.textContent = rows.length ? `${rows.length} reports` : "No reports";
}
async function exportCSV() {
  const role = document.getElementById("role").value;
  const status = document.getElementById("status");
  status.textContent = "Exporting…";
  try {
    const res = await fetch("/api/reports/export", { headers: { "X-Role": role } });
    if (!res.ok) { status.textContent = `Error ${res.status}`; return; }
    const m = (res.headers.get("Content-Disposition") || "").match(/filename="([^"]*)"/);
    const name = m ? m[1] : "reports.csv";
    const blob = new Blob(["\uFEFF", await res.arrayBuffer()], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    status.textContent = `Exported ${name}`;
  } catch {
    status.textContent = "Export failed";
  }
}
document.getElementById("role").addEventListener("change", load);
document.getElementById("export-csv").addEventListener("click", exportCSV);
load();
