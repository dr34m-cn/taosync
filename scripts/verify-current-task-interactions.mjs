import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { createDemoServer, preparePage } from './readme-screenshots.mjs';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const server = await createDemoServer();
const browser = await chromium.launch({
  channel: process.env.SCREENSHOT_BROWSER_EXECUTABLE ? undefined : 'msedge',
  executablePath: process.env.SCREENSHOT_BROWSER_EXECUTABLE || undefined,
  headless: true,
});
const output = path.resolve('build/verification/current-task-interactions');
await mkdir(output, { recursive: true });

// The waiting legend uses this exact palette color. Read canvas pixels to test
// the real legend click without exposing the chart instance in production.
async function waitingLegend(chart) {
  return chart.evaluate(box => {
    const canvas = box.querySelector('canvas');
    const rect = canvas.getBoundingClientRect();
    const ratio = canvas.width / rect.width;
    const height = Math.min(canvas.height, Math.ceil(65 * ratio));
    const { data } = canvas.getContext('2d').getImageData(0, 0, canvas.width, height);
    let count = 0;
    let xSum = 0;
    let ySum = 0;
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < canvas.width; x++) {
        const index = (y * canvas.width + x) * 4;
        if (data[index] === 105 && data[index + 1] === 115 && data[index + 2] === 134 && data[index + 3] === 255) {
          count++;
          xSum += x;
          ySum += y;
        }
      }
    }
    return { count, x: rect.x + xSum / count / ratio, y: rect.y + ySum / count / ratio };
  });
}

try {
  for (const mobile of [false, true]) {
    const { page, context, errors } = await preparePage(browser, server.url, mobile);
    const records = Array.from({ length: 12 }, (_, index) => ({
      fileName: index < 2 ? 'same-name.bin' : `file-${index}.bin`, fileSize: 1024 ** 2,
      srcPath: `/Source/${index}/same-name.bin`, dstPath: `/Cloud/${index}/same-name.bin`,
      type: 0, isPath: 0, createTime: 1800000000, status: 1, progress: 10,
    }));
    let ticks = 0;
    let reorder = false;
    let removed = false;
    let delayedWaiting = null;
    let delayedFailure = null;
    let waitingDelayRequested = false;
    let failureDelayRequested = false;
    await context.route('**/svr/job?**', async route => {
      const query = new URL(route.request().url()).searchParams;
      if (!query.has('current')) return route.fallback();
      assert.equal(route.request().method(), 'GET');
      if (query.has('status')) {
        const status = Number(query.get('status'));
        if (status === 0 && !waitingDelayRequested) {
          waitingDelayRequested = true;
          await new Promise(resolve => { delayedWaiting = resolve; });
        }
        if (status === 7 && !failureDelayRequested) {
          failureDelayRequested = true;
          await new Promise(resolve => { delayedFailure = resolve; });
        }
        return route.fulfill({ json: { code: 200, data: records.map(row => ({ ...row,
          fileName: `status-${status}-${row.fileName}`, status,
        })) } });
      }
      ticks++;
      let doingTask = records.filter((_, index) => !removed || index !== 0);
      if (reorder && !removed) doingTask = [doingTask[1], doingTask[0], ...doingTask.slice(2)];
      await route.fulfill({ json: { code: 200, data: {
        scanFinish: true, createTime: 1800000000, firstSync: 1800000001, duration: 100 + ticks,
        num: { wait: 20 + ticks, running: doingTask.length, success: 3, fail: 1, other: 1 },
        size: { wait: 100000000, running: 12000000, success: 3000000, fail: 1000000, other: 1000000 },
        doingTask: doingTask.map(row => ({ ...row, progress: 10 + ticks })),
      } } });
    });
    const refreshes = async (count = 3) => {
      const target = ticks + count;
      while (ticks < target) {
        await page.waitForResponse(response => response.url().includes('/svr/job?')
          && new URL(response.url()).searchParams.has('current')
          && !new URL(response.url()).searchParams.has('status'));
      }
      await page.waitForTimeout(100);
    };
    const waitFor = async condition => {
      const deadline = Date.now() + 10000;
      while (!condition() && Date.now() < deadline) await page.waitForTimeout(20);
      assert.ok(condition(), 'The requested filter must start loading');
    };
    try {
      await page.goto(server.url + '/#/home/task?jobId=1');
      const panel = page.locator('.task-current');
      const table = panel.locator('.detail-table');
      const chart = panel.locator('.echarts-box');
      await chart.locator('canvas').waitFor();
      await chart.scrollIntoViewIfNeeded();
      await page.evaluate(() => document.fonts.ready);
      const legend = await waitingLegend(chart);
      assert.ok(legend.count > 0, 'Waiting legend must be rendered');
      await page.mouse.click(legend.x, legend.y);
      await page.mouse.move(0, 0);
      await page.waitForTimeout(100);
      assert.equal((await waitingLegend(chart)).count, 0, 'Click must deselect the waiting legend');
      await refreshes();
      assert.equal((await waitingLegend(chart)).count, 0, 'Polling must retain the deselected legend');

      const firstRow = table.locator('.el-table__row').first();
      const initialProgress = await firstRow.locator('.el-progress__text, .el-progress-bar__innerText').innerText();
      await firstRow.locator('.el-table__expand-icon').click();
      await refreshes();
      const expanded = table.locator('.el-table__expanded-cell');
      assert.equal(await expanded.count(), 1, 'Polling must retain row expansion');
      await expanded.getByText('/Cloud/0/same-name.bin', { exact: true }).waitFor();
      assert.notEqual(await firstRow.locator('.el-progress__text, .el-progress-bar__innerText').innerText(), initialProgress,
        'Data must keep refreshing while the row is expanded');
      reorder = true;
      await refreshes(1);
      assert.equal(await expanded.count(), 1, 'Reordering must retain the expanded record');
      await expanded.getByText('/Cloud/0/same-name.bin', { exact: true }).waitFor();
      await table.locator('.el-table__expand-icon--expanded').click();
      await refreshes(1);
      assert.equal(await expanded.count(), 0, 'Polling must retain a manually collapsed row');
      await table.locator('.el-table__row').nth(1).locator('.el-table__expand-icon').click();
      await expanded.getByText('/Cloud/0/same-name.bin', { exact: true }).waitFor();
      removed = true;
      await refreshes(1);
      assert.equal(await expanded.count(), 0, 'A completed row must not leave another row expanded');
      await panel.locator('.el-pager .number').filter({ hasText: /^2$/ }).click();
      await refreshes();
      assert.equal(await panel.locator('.el-pager .number.is-active').innerText(), '2', 'Polling must retain the selected page');
      await table.getByText('file-11.bin', { exact: true }).waitFor();

      await panel.locator('.task-left-item').filter({ hasText: /^等待中$/ }).click();
      await page.waitForFunction(() => document.querySelector('.task-left-item.is-current')?.textContent.trim() === '等待中');
      await waitFor(() => delayedWaiting);
      await panel.locator('.task-left-item').filter({ hasText: /^失败$/ }).click();
      delayedWaiting();
      delayedWaiting = null;
      await waitFor(() => delayedFailure);
      assert.equal(await table.getByText(/^status-0-/).count(), 0, 'A stale response must not appear while the new filter is loading');
      delayedFailure();
      delayedFailure = null;
      await table.getByText('status-7-same-name.bin', { exact: true }).first().waitFor();
      await refreshes();
      assert.equal(await table.getByText(/^status-0-/).count(), 0, 'A stale response must not overwrite the current filter');
      assert.equal(await panel.locator('.el-pager .number.is-active').innerText(), '1', 'Changing filters must reset the pager and data together');
      await table.locator('.el-table__row').first().locator('.el-table__expand-icon').click();
      await refreshes();
      assert.equal(await expanded.count(), 1, 'Filtered rows must retain expansion too');

      await panel.scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(output, mobile ? 'mobile.png' : 'desktop.png') });
      assert.deepEqual(errors, []);
      console.log(`${mobile ? 'mobile' : 'desktop'}: legend selection, row expansion, live progress, pagination and filter race passed`);
    } finally {
      if (delayedWaiting) delayedWaiting();
      if (delayedFailure) delayedFailure();
      await context.close();
    }
  }
} finally {
  await browser.close();
  await server.close();
}
