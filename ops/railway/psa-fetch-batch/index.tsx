/** @jsx jsx */
/** @jsxImportSource hono/jsx */
import { Hono } from "hono";

const app = new Hono();

const DEFAULT_CERTS = [
  "160349012",
  "152886233",
  "113437109",
  "152886256",
  "62398872",
  "150446783",
  "165543324",
];

const CERT_PATTERN = /^\d{7,10}$/;

function pick(source: unknown, names: string[]): unknown {
  if (!source || typeof source !== "object") return null;
  const object = source as Record<string, unknown>;
  for (const name of names) {
    if (object[name] !== undefined && object[name] !== null && object[name] !== "") {
      return object[name];
    }
  }
  return null;
}

function certPayload(data: unknown): Record<string, unknown> {
  if (!data || typeof data !== "object") return {};
  const root = data as Record<string, unknown>;
  const nested = pick(root, ["PSACert", "psaCert", "cert", "Cert"]);
  return nested && typeof nested === "object"
    ? nested as Record<string, unknown>
    : root;
}

function collectImageUrls(
  value: unknown,
  path = "",
  found: Array<{ key: string; url: string }> = [],
): Array<{ key: string; url: string }> {
  if (!value || typeof value !== "object") return found;
  if (Array.isArray(value)) {
    value.forEach((entry, index) =>
      collectImageUrls(entry, path ? `${path}[${index}]` : `[${index}]`, found)
    );
    return found;
  }
  for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
    const nextPath = path ? `${path}.${key}` : key;
    if (
      typeof entry === "string"
      && /^https:\/\//i.test(entry)
      && /image|scan|photo|front|back|reverse/i.test(nextPath)
    ) {
      found.push({ key: nextPath, url: entry });
    } else if (entry && typeof entry === "object") {
      collectImageUrls(entry, nextPath, found);
    }
  }
  return found;
}

function imageFor(
  images: Array<{ key: string; url: string }>,
  pattern: RegExp,
): string | null {
  return images.find((image) => pattern.test(image.key))?.url || null;
}

function normalizeCert(cert: string, data: unknown) {
  const root = data && typeof data === "object"
    ? data as Record<string, unknown>
    : {};
  const payload = certPayload(data);
  const imageFields = collectImageUrls(data);
  const isValidRequest = pick(root, ["IsValidRequest", "isValidRequest"]);
  const serverMessage = pick(root, ["ServerMessage", "serverMessage"]);
  const verified = isValidRequest === true
    && String(serverMessage || "").toLowerCase().includes("successful");

  const front = imageFor(imageFields, /front/i);
  const back = imageFor(imageFields, /back|reverse/i);
  const fallbackUrls = [...new Set(imageFields.map((image) => image.url))];

  return {
    cert_number: String(
      pick(payload, ["CertNumber", "cert_number", "cert_id", "CertNo"]) || cert
    ),
    verified,
    server_message: serverMessage || null,
    year: pick(payload, ["Year", "year"]),
    set_brand: pick(payload, ["Brand", "BrandTitle", "set_name", "brand"]),
    subject: pick(payload, ["Subject", "subject", "card_title", "title"]),
    card_number: pick(payload, ["CardNumber", "card_number"]),
    variety: pick(payload, ["Variety", "VarietyPedigree", "variety"]),
    category: pick(payload, ["Category", "category"]),
    grade: pick(payload, ["CardGrade", "Grade", "grade", "grade_value"]),
    grade_description: pick(payload, ["GradeDescription", "grade_description"]),
    language_printing: pick(payload, ["Language", "language", "Printing", "printing"]),
    front_image_url: front || fallbackUrls[0] || null,
    back_image_url: back || fallbackUrls.find((url) => url !== front) || fallbackUrls[1] || null,
    image_fields: imageFields,
  };
}

async function lookupCert(cert: string, token: string) {
  const response = await fetch(
    `https://api.psacard.com/publicapi/cert/GetByCertNumber/${cert}`,
    {
      headers: {
        Authorization: `bearer ${token}`,
        Accept: "application/json",
      },
    },
  );

  if (!response.ok) {
    return {
      cert_number: cert,
      verified: false,
      error: `HTTP ${response.status}`,
    };
  }

  const data = await response.json();
  return normalizeCert(cert, data);
}

app.get("/", async (c) => {
  const token = Bun.env.PSA_PUBLIC_API_TOKEN || Bun.env.TCG_PARSE_API_KEY;
  if (!token) {
    return c.json({ error: "PSA API token not configured" }, 503);
  }

  const requested = String(c.req.query("cert") || "").trim();
  if (requested && !CERT_PATTERN.test(requested)) {
    return c.json({ error: "cert must be 7-10 digits" }, 422);
  }

  const certs = requested ? [requested] : DEFAULT_CERTS;
  const results = [];
  for (const cert of certs) {
    try {
      results.push(await lookupCert(cert, token));
    } catch (error) {
      results.push({
        cert_number: cert,
        verified: false,
        error: error instanceof Error ? error.message : "Unknown error",
      });
    }
  }

  return c.json(requested ? results[0] : results);
});

export default app;
