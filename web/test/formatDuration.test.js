import assert from 'node:assert/strict';
import test from 'node:test';
import { formatDuration } from '../src/utils/utils.js';

test('task durations carry seconds into minutes, hours and whole days', () => {
  const units = { 'time.day': '天', 'time.hour': '小时', 'time.minute': '分钟', 'time.second': '秒' };
  for (const [seconds, text] of [
    [0, '0秒'], [59, '59秒'], [60, '1分钟'], [61, '1分钟 1秒'],
    [3599, '59分钟 59秒'], [3600, '1小时'], [86400, '1天'],
    [90061, '1天 1小时 1分钟 1秒'], [366 * 86400 + 1, '366天 1秒'],
  ]) {
    assert.equal(formatDuration(seconds, key => units[key]), text);
  }
});
