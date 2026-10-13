// Appels à l'API du serveur local.
async function request(url, options = {}) {
  const r = await fetch(url, options);
  if (!r.ok) throw new Error(`${r.status} ${(await r.json().catch(() => ({}))).detail || r.statusText}`);
  return r.json();
}

const postImage = (url, blob) => {
  const body = new FormData();
  body.append("image", blob, "frame.jpg");
  return request(url, { method: "POST", body });
};

const postJson = (url, data) =>
  request(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

export const api = {
  scan: (blob) => postImage("/api/scan", blob),
  detect: (blob) => postImage("/api/detect", blob),
  undo: (scanId) => request(`/api/scans/${scanId}/undo`, { method: "POST" }),
  reassign: (scanId, cardId, lang) => postJson(`/api/scans/${scanId}/reassign`, { card_id: cardId, lang }),
  addManual: (cardId, lang) => postJson("/api/manual", { card_id: cardId, lang }),
  search: (q) => request("/api/search?q=" + encodeURIComponent(q)),
  stats: () => request("/api/stats"),
  recent: (limit = 20) => request(`/api/recent?limit=${limit}`),
};
