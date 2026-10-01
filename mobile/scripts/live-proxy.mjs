const upstream = "https://drop-rate-api-live-production.up.railway.app";
const origin = "http://127.0.0.1:8085";
export async function liveProxy(req, res, transport = fetch) {
  const deny = (status, detail) => {
    res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    res.end(JSON.stringify({ detail }));
  };
  if (req.headers.host !== "127.0.0.1:8085" || (req.headers.origin && req.headers.origin !== origin) || req.headers["sec-fetch-site"] === "cross-site") {
    deny(403, "Only the local preview can access this test service."); return;
  }
  const url = new URL(req.url, origin);
  const login = req.method === "POST" && url.pathname === "/api/v1/public/owner-session" && !url.search;
  if ((!login && req.method !== "GET") || !url.pathname.startsWith("/api/v1/") || /%|\\|\.\./.test(url.pathname) || (login && req.headers.origin !== origin)) {
    deny(403, "Live test mode allows sign-in and viewing only. Changes are blocked."); return;
  }
  try {
    let body;
    if (login) {
      const chunks = []; let size = 0;
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 16384) { deny(413, "Request too large."); return; }
        chunks.push(chunk);
      }
      body = Buffer.concat(chunks);
    }
    const headers = { Accept: "application/json" };
    if (login) headers["Content-Type"] = "application/json";
    if (req.headers.authorization) headers.Authorization = req.headers.authorization;
    const response = await transport(upstream + url.pathname + url.search, {
      method: req.method, headers, body, redirect: "error", signal: AbortSignal.timeout(90000),
    });
    res.writeHead(response.status, {
      "Content-Type": response.headers.get("content-type") || "application/json",
      "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    });
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch {
    if (!res.headersSent) deny(502, "Unable to reach the live service. Please try again.");
    else res.end();
  }
}
