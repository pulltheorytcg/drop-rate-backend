"use strict";

// A display-only source lookup, separate from publisher/approved copy media.
// Never fetch these URLs with app credentials or send them to an image proxy.
window.DropRateBookArtwork = Object.freeze({
  reference(item, detail = false) {
    const cover = item?.community_cover;
    if (item?.product_type !== "COMIC" || cover?.kind !== "OPEN_LIBRARY_EDITION_REFERENCE"
        || cover.provider !== "OPEN_LIBRARY" || cover.scope !== "COMMUNITY_EDITION"
        || cover.status !== "REFERENCE_ONLY" || !/^OL[1-9][0-9]*M$/.test(cover.edition_id || "")) return null;
    const source = `https://openlibrary.org/books/${cover.edition_id}`;
    const base = `https://covers.openlibrary.org/b/olid/${cover.edition_id}`;
    if (cover.source_url !== source || cover.image_url !== `${base}-M.jpg?default=false`
        || cover.detail_image_url !== `${base}-M.jpg?default=false`) return null;
    const language = item.language || item.catalogue_language || item.book_details?.language;
    if (language && language !== cover.language) return null;
    return {source_url: source, image_url: detail ? cover.detail_image_url : cover.image_url};
  },
  credit(cover, className = "") {
    const note = document.createElement("p"); note.className = ["book-cover-reference", className].filter(Boolean).join(" ");
    note.append(document.createTextNode("Cover reference · "));
    const link = document.createElement("a"); link.textContent = "Open Library";
    link.href = cover.source_url; link.target = "_blank"; link.rel = "noopener noreferrer";
    // Source inspection must not select a product or open its intake form.
    link.addEventListener("click", event => event.stopPropagation());
    note.append(link, document.createTextNode(" · Cover may vary"));
    return note;
  }
});
