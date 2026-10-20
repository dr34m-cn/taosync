import test from "node:test";
import assert from "node:assert/strict";

import {
  bytesFromFileSize,
  fileSizeInputFromBytes,
  isFileSizeBoundaryValid,
  isFileSizeRangeValid,
} from "../src/utils/fileSizeFilter.js";

test("converts all supported units to integer bytes", () => {
  assert.equal(bytesFromFileSize(12, "B"), 12);
  assert.equal(bytesFromFileSize(1.5, "KB"), 1536);
  assert.equal(bytesFromFileSize(1.5, "MB"), 1572864);
  assert.equal(bytesFromFileSize(2, "GB"), 2147483648);
  assert.equal(bytesFromFileSize(null, "MB"), null);
});

test("round-trips stored bytes without changing the threshold", () => {
  for (const bytes of [0, 1, 1025, 1572864, 2147483648]) {
    const input = fileSizeInputFromBytes(bytes);
    assert.equal(bytesFromFileSize(input.value, input.unit), bytes);
  }
});

test("rejects invalid boundaries and reversed ranges", () => {
  assert.equal(isFileSizeBoundaryValid(null), true);
  assert.equal(isFileSizeBoundaryValid(0), true);
  assert.equal(isFileSizeBoundaryValid(-1), false);
  assert.equal(isFileSizeBoundaryValid(1.5), false);
  assert.equal(isFileSizeRangeValid(null, null), true);
  assert.equal(isFileSizeRangeValid(100, 100), true);
  assert.equal(isFileSizeRangeValid(101, 100), false);
});
