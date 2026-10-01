// Match the browser batch scanner's longest-edge limit without upscaling.
export function captureSize(width: number, height: number) {
  if (
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width <= 0 ||
    height <= 0
  )
    throw new Error(
      "The photo dimensions could not be read. Please retake it.",
    );
  const scale = Math.min(1, 1500 / Math.max(width, height));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}
