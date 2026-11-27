import assert from "node:assert/strict";
import test from "node:test";
import {
  formatRemoteRootLabel,
  joinRemotePath,
  normalizeRemoteRoot,
} from "../src/utils/remoteFolderPicker.js";
import { parseSize } from "../src/utils/utils.js";

test("normalizeRemoteRoot cleans separators and rejects dot segments", () => {
  assert.equal(normalizeRemoteRoot(""), "/");
  assert.equal(normalizeRemoteRoot("/"), "/");
  assert.equal(normalizeRemoteRoot("photos/2026/"), "/photos/2026");
  assert.equal(normalizeRemoteRoot("\\photos\\2026\\"), "/photos/2026");
  assert.equal(normalizeRemoteRoot("/photos/../secret"), "/");
  assert.equal(normalizeRemoteRoot("/./photos"), "/");
});

test("formatRemoteRootLabel prefixes SMB share and keeps FTP/SFTP root clean", () => {
  assert.equal(formatRemoteRootLabel("smb", "Media", "/"), "Media:/");
  assert.equal(formatRemoteRootLabel("smb", "Media", "/photos/2026"), "Media:/photos/2026");
  assert.equal(formatRemoteRootLabel("ftp", "", "/"), "/");
  assert.equal(formatRemoteRootLabel("ftp", "", "/incoming/"), "/incoming");
  assert.equal(formatRemoteRootLabel("sftp", "", "/srv/data"), "/srv/data");
});

test("joinRemotePath resolves selections from either server root or a custom base", () => {
  assert.equal(joinRemotePath("/", "/"), "/");
  assert.equal(joinRemotePath("/", "/videos"), "/videos");
  assert.equal(joinRemotePath("/users/alice", "/"), "/users/alice");
  assert.equal(joinRemotePath("/users/alice", "/photos/2026"), "/users/alice/photos/2026");
  assert.equal(joinRemotePath("\\users\\alice\\", "/photos/"), "/users/alice/photos");
});

test("parseSize formats small and gigabyte rapid-upload totals with adaptive units", () => {
  assert.equal(parseSize(0), "0 B");
  assert.equal(parseSize(512), "512 B");
  assert.equal(parseSize(3072), "3 KB");
  assert.equal(parseSize(1536 * 1024), "1.5 MB");
  assert.equal(parseSize(2 * 1024 ** 3), "2 GB");
});
