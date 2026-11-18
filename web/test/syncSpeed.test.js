import test from "node:test";
import assert from "node:assert/strict";
import { averageSyncSpeed } from "../src/utils/syncSpeed.js";

test("average speed excludes the initial scan and uses precise sync duration", () => {
  const current = { createTime: 100, duration: 610, firstSync: 700, syncDuration: 10.25 };
  assert.equal(averageSyncSpeed(current, 1025), 100);
  assert.equal(averageSyncSpeed({ ...current, duration: 3610 }, 1025), 100);
});

test("scan-only and just-started runs have zero average speed", () => {
  assert.equal(averageSyncSpeed({ syncDuration: 0 }, 1024), 0);
  assert.equal(averageSyncSpeed({ createTime: 100, duration: 600, firstSync: null }, 1024), 0);
});

test("older servers still exclude scanning time", () => {
  assert.equal(averageSyncSpeed({ createTime: 100, duration: 610, firstSync: 700 }, 1000), 100);
});

test("rapid uploads count toward completion but never inflate average speed", () => {
  const current = { syncDuration: 4, rapidUploadBytes: 100 * 1024 ** 2 };
  assert.equal(averageSyncSpeed(current, current.rapidUploadBytes + 2048), 512);
  assert.equal(averageSyncSpeed(current, current.rapidUploadBytes), 0);
});
