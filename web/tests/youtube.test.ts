/** tests for src/lib/youtube.ts: the "▶ Watch @ 3:10" text and link. */

import { describe, expect, test } from "vitest";

import { formatTime, watchUrl } from "../src/lib/youtube";

describe("formatTime", () => {
  test.each([
    [0, "0:00"],
    [5, "0:05"],
    [190, "3:10"],
    [3599, "59:59"],
    [3725, "1:02:05"],
  ])("%i seconds -> %s", (seconds, expected) => {
    expect(formatTime(seconds)).toBe(expected);
  });
});

describe("watchUrl", () => {
  test("starts 5 seconds early so you hear the lead-in", () => {
    expect(watchUrl("abc123XYZ00", 190)).toBe("https://www.youtube.com/watch?v=abc123XYZ00&t=185s");
  });

  test("never goes below the start of the video", () => {
    expect(watchUrl("abc123XYZ00", 2)).toBe("https://www.youtube.com/watch?v=abc123XYZ00&t=0s");
  });

  test("no time means the start of the video", () => {
    expect(watchUrl("abc123XYZ00", null)).toBe("https://www.youtube.com/watch?v=abc123XYZ00");
  });
});
