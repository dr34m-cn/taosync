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
const output = path.resolve(process.env.TAO_VERIFY_OUTPUT || 'build/verification/engine-transfer');
await mkdir(output, { recursive: true });

try {
  for (const mobile of [false, true]) {
    const state = await preparePage(browser, server.url, mobile);
    const { page, context } = state;
    const engine = { id: 1, engineType: 'taosync', displayName: 'TaoSync', directoryCount: 1, copyConcurrency: 5 };
    const cloud = {
      id: 11, engineId: 1, name: 'Cloud', driverType: 'aliyun',
      config: { auth_mode: 'service', drive_type: 'resource', root_folder_id: 'root', root_folder_path: '/', remove_way: 'trash' },
      secretState: { refresh_token: true, refresh_proof: true },
    };
    const browses = [];
    let saved = null;
    await context.route('**/svr/alist', async route => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON();
        assert.equal(body.id, 1);
        engine.copyConcurrency = body.copyConcurrency;
      }
      await route.fulfill({ json: { code: 200, data: [engine] } });
    });
    await context.route('**/svr/storage**', async route => {
      const request = route.request();
      let data = [cloud];
      if (request.method() === 'PUT') saved = request.postDataJSON();
      if (request.method() === 'POST') {
        const body = request.postDataJSON();
        assert.equal(body.action, 'aliyunBrowse');
        browses.push(body);
        const directories = body.parentId === 'root'
          ? [{ id: body.config.drive_type === 'backup' ? 'backup-folder' : 'photos', name: body.config.drive_type === 'backup' ? 'Archive' : 'Photos' }]
          : body.parentId === 'photos' ? [{ id: 'year', name: '2026' }] : [];
        data = { directories };
      }
      await route.fulfill({ json: { code: 200, data } });
    });
    try {
      await page.goto(server.url + '/#/engine');
      await page.getByRole('button', { name: '并行复制数', exact: true }).click();
      const settings = page.getByRole('dialog', { name: '并行复制数', exact: true });
      assert.equal(await settings.getByRole('spinbutton').inputValue(), '5');
      await settings.getByRole('spinbutton').fill('8');
      await settings.getByRole('button', { name: '确定', exact: true }).click();
      await settings.waitFor({ state: 'hidden' });
      await page.getByRole('button', { name: '并行复制数', exact: true }).click();
      assert.equal(await settings.getByRole('spinbutton').inputValue(), '8');
      await page.screenshot({ path: path.join(output, 'concurrency-' + (mobile ? 'mobile' : 'desktop') + '.png') });
      await settings.getByRole('button', { name: '取消', exact: true }).click();
      await page.getByRole('button', { name: '目录管理', exact: true }).click();
      await page.locator('.mount-item').getByRole('button', { name: '编辑', exact: true }).click();
      const form = page.locator('.mount-editor-dialog');
      assert.equal(await form.getByText('根文件夹 ID', { exact: true }).count(), 0);
      const root = form.locator('.el-form-item').filter({ has: page.locator('.el-form-item__label', { hasText: '根文件夹' }) });
      await root.locator('.el-select').click();
      await page.locator('.el-select-dropdown:visible .el-tree-node__expand-icon').first().click();
      await page.getByText('Photos', { exact: true }).waitFor();
      const photos = page.locator('.el-select-dropdown:visible .el-tree-node__content').filter({ hasText: 'Photos' });
      await photos.locator('.el-tree-node__expand-icon').click();
      await page.getByText('2026', { exact: true }).click();
      await page.locator('.el-select-dropdown:visible').waitFor({ state: 'hidden' });
      assert.equal(browses[0].engineId, 1);
      assert.equal(browses[0].mountId, 11);
      await page.screenshot({ path: path.join(output, 'root-folder-' + (mobile ? 'mobile' : 'desktop') + '.png') });
      await form.getByRole('button', { name: '确定', exact: true }).click();
      await form.waitFor({ state: 'hidden' });
      assert.equal(saved.config.root_folder_id, 'year');
      assert.equal(saved.config.root_folder_path, '/Photos/2026');
      await page.locator('.mount-item').getByRole('button', { name: '编辑', exact: true }).click();
      const space = form.locator('.el-form-item').filter({ has: page.locator('.el-form-item__label', { hasText: '网盘空间' }) });
      await space.locator('.el-select').click();
      await page.getByRole('option', { name: '备份盘', exact: true }).click();
      await root.locator('.el-select').click();
      await page.locator('.el-select-dropdown:visible .el-tree-node__expand-icon').first().click();
      await page.getByText('Archive', { exact: true }).waitFor();
      assert.equal(browses.at(-1).config.drive_type, 'backup');
      assert.equal(browses.at(-1).config.root_folder_id, 'root');
      assert.equal(await page.getByText('Photos', { exact: true }).count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await form.getByRole('button', { name: '取消', exact: true }).click();
      cloud.config = { ...cloud.config, auth_mode: undefined, auth_service_url: 'https://auth.example.test', root_folder_id: 'legacy-folder', root_folder_path: undefined };
      await page.reload();
      await page.getByRole('button', { name: '目录管理', exact: true }).click();
      await page.locator('.mount-item').getByRole('button', { name: '编辑', exact: true }).click();
      assert.equal(await form.getByText('legacy-folder', { exact: true }).count(), 0);
      await form.getByRole('button', { name: '确定', exact: true }).click();
      await form.waitFor({ state: 'hidden' });
      assert.equal(saved.config.root_folder_id, 'legacy-folder');
      assert.deepEqual(state.errors, []);
      console.log((mobile ? 'mobile' : 'desktop') + ': concurrency settings, nested folder selection, space change passed');
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
  await server.close();
}
