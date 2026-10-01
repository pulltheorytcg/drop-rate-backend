import { expect, it } from "vitest";
import { captureSize } from "../src/lib/capture";

it("caps portrait and landscape images by their longest edge", () => {
  expect(captureSize(3000, 4000)).toEqual({ width: 1125, height: 1500 });
  expect(captureSize(4000, 3000)).toEqual({ width: 1500, height: 1125 });
  expect(captureSize(2000, 2000)).toEqual({ width: 1500, height: 1500 });
});
it("does not enlarge small photos or distort their shape", () => {
  expect(captureSize(700, 980)).toEqual({ width: 700, height: 980 });
  expect(captureSize(1500, 1000)).toEqual({ width: 1500, height: 1000 });
});
it("rejects missing or invalid dimensions before image processing", () => {
  for (const value of [0, -1, NaN, Infinity])
    expect(() => captureSize(value, 1000)).toThrow();
});
