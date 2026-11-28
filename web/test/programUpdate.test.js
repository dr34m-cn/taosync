import test from 'node:test';
import assert from 'node:assert/strict';

import {
  AUTO_SOURCE_OPTION,
  LATEST_STABLE_OPTION,
  buildSourceOptions,
  buildVersionOptions,
  formatByteSize,
  formatSourceLabel,
  reconcileSelectedSource,
} from '../src/utils/programUpdate.js';

const sampleReleases = {
  currentVersion: 'v0.5.1',
  latestVersion: 'v0.5.2',
  latestAvailable: true,
  target: 'linux-amd64',
  versions: [
    {
      version: 'v0.5.2',
      channel: 'stable',
      isLatestStable: true,
      filename: 'taoSync-v0.5.2-linux-amd64.tar.gz',
      sources: [
        { id: 'github', name: 'GitHub Release', labels: { 'zh-CN': 'GitHub Release', en: 'GitHub Release' } },
        { id: 'r2', name: 'Cloudflare R2', labels: { 'zh-CN': 'Cloudflare R2', en: 'Cloudflare R2' } },
      ],
    },
    {
      version: 'v0.5.3-dev1',
      channel: 'dev',
      isLatestStable: false,
      filename: 'taoSync-v0.5.3-dev1-linux-amd64.tar.gz',
      sources: [
        { id: 'r2', name: 'Cloudflare R2', labels: { 'zh-CN': 'Cloudflare R2', en: 'Cloudflare R2' } },
      ],
    },
  ],
};

test('version options always place latest stable at top', () => {
  const options = buildVersionOptions(sampleReleases);
  assert.equal(options[0].value, LATEST_STABLE_OPTION);
  assert.equal(options[0].isLatestOption, true);
  assert.equal(options[0].version, 'v0.5.2');
  assert.deepEqual(options.slice(1).map(item => item.value), ['v0.5.2', 'v0.5.3-dev1']);

  const emptyOptions = buildVersionOptions(null);
  assert.equal(emptyOptions.length, 1);
  assert.equal(emptyOptions[0].value, LATEST_STABLE_OPTION);
  assert.equal(emptyOptions[0].available, false);
});

test('source options always place auto source at top and follow selected version dynamically', () => {
  const latestSources = buildSourceOptions(sampleReleases, LATEST_STABLE_OPTION);
  assert.deepEqual(latestSources.map(item => item.value), [AUTO_SOURCE_OPTION, 'github', 'r2']);

  const devSources = buildSourceOptions(sampleReleases, 'v0.5.3-dev1');
  assert.deepEqual(devSources.map(item => item.value), [AUTO_SOURCE_OPTION, 'r2']);

  const extended = {
    ...sampleReleases,
    versions: [
      {
        ...sampleReleases.versions[0],
        sources: [
          ...sampleReleases.versions[0].sources,
          { id: 'cnb', name: 'CNB', labels: { 'zh-CN': 'CNB 镜像', en: 'CNB Mirror' } },
        ],
      },
    ],
  };
  const dynamicSources = buildSourceOptions(extended, LATEST_STABLE_OPTION);
  assert.deepEqual(dynamicSources.map(item => item.value), [AUTO_SOURCE_OPTION, 'github', 'r2', 'cnb']);
  assert.equal(formatSourceLabel(dynamicSources[3], 'zh-CN'), 'CNB 镜像');
  assert.equal(formatSourceLabel(dynamicSources[3], 'en'), 'CNB Mirror');
});

test('reconcileSelectedSource resets to auto when chosen source disappears on version change', () => {
  assert.equal(reconcileSelectedSource(sampleReleases, 'v0.5.2', 'github'), 'github');
  assert.equal(reconcileSelectedSource(sampleReleases, 'v0.5.3-dev1', 'github'), AUTO_SOURCE_OPTION);
  assert.equal(reconcileSelectedSource(sampleReleases, 'v0.5.3-dev1', 'r2'), 'r2');
  assert.equal(reconcileSelectedSource(sampleReleases, 'v0.5.3-dev1', AUTO_SOURCE_OPTION), AUTO_SOURCE_OPTION);
});

test('formatByteSize formats readable binary units', () => {
  assert.equal(formatByteSize(512), '512 B');
  assert.equal(formatByteSize(2048), '2.0 KB');
  assert.equal(formatByteSize(15.5 * 1024 * 1024), '15.5 MB');
});
