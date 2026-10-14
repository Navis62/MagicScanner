// Appels à l'API du serveur local.
async function request(url, options = {}) {
  const r = await fetch(url, options);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

const postImage = (url, blob, foil = false, price = 0.2) => {
  const body = new FormData();
  body.append("image", blob, "frame.jpg");
  body.append("foil", foil);
  body.append("price", price);
  return request(url, { method: "POST", body });
};

const postJson = (url, data) =>
  request(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

export const api = {
  scan: (blob, foil, price) => postImage("/api/scan", blob, foil, price),
  detect: (blob) => postImage("/api/detect", blob),
  undo: () => request("/api/undo", { method: "POST" }),
  reassign: (scanId, cardId, lang, foil = null, price = null) =>
    postJson(`/api/scans/${scanId}/reassign`, { card_id: cardId, lang, foil, price }),
  addManual: (cardId, lang, foil, price) => postJson("/api/manual", { card_id: cardId, lang, foil, price }),
  search: (q) => request("/api/search?q=" + encodeURIComponent(q)),
  stats: () => request("/api/stats"),
  recent: (limit = 20) => request(`/api/recent?limit=${limit}`),
  exportPowertools: async () => {
    const r = await fetch("/api/export");
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return { blob: await r.blob(), lines: +r.headers.get("X-Export-Lines"), skipped: +r.headers.get("X-Export-Skipped") };
  },
  refreshPrices: () => request("/api/prices/refresh", { method: "POST" }),
  publishStatus: () => request("/api/publish"),
  publish: (options = {}) => postJson("/api/publish", options),
  publishReset: () => request("/api/publish/reset", { method: "POST" }),
  publishStop: () => request("/api/publish/stop", { method: "POST" }),
};
