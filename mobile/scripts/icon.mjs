import sharp from "sharp";
await sharp("assets/app-icon.svg").png().toFile("assets/icon.png");
