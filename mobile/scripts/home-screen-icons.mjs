// Package the existing storefront artwork on square app-icon canvases.
import { readFile } from 'node:fs/promises';
import sharp from 'sharp';
const assets = new URL('../../backend/app/static/brand-assets/', import.meta.url);
const logo = (await readFile(new URL('storefront-logo.png', assets))).toString('base64');
const svg = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024"><rect width="1024" height="1024" fill="white"/><image href="data:image/png;base64,${logo}" x="82" y="219" width="860" height="586" preserveAspectRatio="xMidYMid meet"/></svg>`);
for (const size of [180, 192, 512]) {
  await sharp(svg).resize(size, size).png().toFile(new URL(`app-icon-${size}.png`, assets).pathname);
}

await sharp(svg).png().toFile(new URL("../assets/icon.png", import.meta.url).pathname);
