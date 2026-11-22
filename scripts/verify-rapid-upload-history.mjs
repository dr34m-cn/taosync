import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createDemoServer, preparePage } from './readme-screenshots.mjs';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const server = await createDemoServer();
const browser = await chromium.launch(process.env.SCREENSHOT_BROWSER_EXECUTABLE
  ? { executablePath: process.env.SCREENSHOT_BROWSER_EXECUTABLE } : { channel: 'msedge' });
const GiB = 1024 ** 3;
const rows = Array.from({ length: 16 }, (_, i) => ({
  id: i + 1, fileName: `item-${i + 1}.bin`, fileSize: GiB, rapidUpload: Number(i === 2 || i === 13),
  type: 0, status: 2, srcPath: '/source', dstPath: '/target', createTime: 100,
}));

try {
  for (const [mobile, language] of [[false, 'zh-CN'], [false, 'en'], [true, 'zh-CN'], [true, 'en']]) {
    const english = language === 'en';
    const { page, context, errors } = await preparePage(browser, server.url, mobile, language);
    let lastQuery;
    await context.route('**/svr/job?**', route => {
      const query = new URL(route.request().url()).searchParams;
      if (query.has('taskId')) {
        lastQuery = query;
        const matches = query.has('rapidUpload') ? rows.filter(item => item.rapidUpload) : rows;
        const size = Number(query.get('pageSize'));
        const start = (Number(query.get('pageNum')) - 1) * size;
        return route.fulfill({ json: { code: 200, data: { count: matches.length, dataList: matches.slice(start, start + size) } } });
      }
      if (query.has('id') && !query.has('current')) {
        const task = { status: 2, runTime: 100, fileStats: { copy: { count: 16, size: 16 * GiB } } };
        return route.fulfill({ json: { code: 200, data: { count: 2, dataList: [
          { ...task, id: 1, fileStats: { ...task.fileStats, rapidUpload: { count: 2, size: 2 * GiB } } },
          { ...task, id: 2 },
        ] } } });
      }
      return route.fallback();
    });
    await page.goto(`${server.url}/#/home/task/detail?taskId=208`);
    await page.getByText('item-1.bin', { exact: true }).waitFor();
    await page.locator('.el-pagination .btn-next').click();
    await page.getByText('item-11.bin', { exact: true }).waitFor();
    const filter = page.locator('.el-select').filter({ has: page.getByRole('combobox', { name: english ? 'Transfer method' : '传输方式' }) });
    await filter.click();
    await page.getByRole('option', { name: english ? 'Instant uploads only' : '仅看秒传' }).click();
    const badges = page.getByText(english ? 'Instant upload' : '秒传', { exact: true });
    await badges.nth(1).waitFor();
    assert.equal(await badges.count(), 2);
    assert.equal(lastQuery.get('pageNum'), '1');
    assert.equal(lastQuery.get('rapidUpload'), '1');
    assert.equal(await page.getByText('item-11.bin', { exact: true }).count(), 0);
    await filter.click();
    await page.getByRole('option', { name: english ? 'All transfer methods' : '全部传输方式' }).click();
    await page.getByText('item-1.bin', { exact: true }).waitFor();
    assert.ok(!lastQuery.has('rapidUpload'));

    await page.goto(`${server.url}/#/home/task?jobId=2`);
    const stats = page.locator('details.history-stats');
    await stats.first().locator('summary').click();
    assert.match(await stats.first().innerText(), english ? /2 files · 2\.00 GB/ : /2 个文件 · 2\.00 GB/);
    assert.match(await stats.first().locator('summary').innerText(), english ? /Processed 16 files/ : /16 个文件/);
    if (english) assert.doesNotMatch(await stats.first().innerText(), /[\u3400-\u9fff]/);
    assert.equal(await stats.nth(1).getByText(english ? 'Instant upload' : '秒传', { exact: true }).count(), 0);
    assert.deepEqual(errors, []);
    await context.close();
    console.log(`${mobile ? 'Mobile' : 'Desktop'} ${language} rapid upload filtering and statistics passed`);
  }
} finally {
  await browser.close();
  await server.close();
}
