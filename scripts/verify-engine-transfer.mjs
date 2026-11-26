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
const waitForDialogs = page => page.waitForFunction(() =>
  !document.querySelector('[class*="-enter-active"], [class*="-leave-active"]'));

try {
  for (const mobile of [false, true]) {
    const state = await preparePage(browser, server.url, mobile);
    const { page, context } = state;
    const engine = { id: 1, engineType: 'taosync', displayName: 'TaoSync', directoryCount: 2 };
    const cloud = {
      id: 11, engineId: 1, name: 'Cloud', driverType: 'aliyun', copyConcurrency: 5,
      config: { auth_mode: 'service', drive_type: 'resource', root_folder_id: 'root', root_folder_path: '/', remove_way: 'trash' },
      secretState: { refresh_token: true, refresh_proof: true },
    };
    const archive = { id: 12, engineId: 1, name: 'Archive', driverType: 'local', copyConcurrency: 2, config: { root_path: 'D:\\Archive' } };
    const browses = [];
    const operations = [];
    const cloudFiles = {
      '/Cloud': [
        { name: 'ArchiveFolder', is_dir: true, size: null },
        { name: 'report.txt', is_dir: false, size: 42, created_at: '2020-01-01T00:00:00Z', modified_at: '2021-01-01T00:00:00Z' },
      ],
      '/Cloud/ArchiveFolder': [],
    };
    let saved = null;
    await context.route('**/svr/alist', async route => {
      assert.equal(route.request().method(), 'GET');
      await route.fulfill({ json: { code: 200, data: [engine] } });
    });
    await context.route('**/svr/storage**', async route => {
      const request = route.request();
      let data = [cloud, archive];
      if (request.method() === 'PUT') {
        saved = request.postDataJSON();
        const mount = saved.id === cloud.id ? cloud : archive;
        mount.copyConcurrency = saved.copyConcurrency;
        if (saved.config) mount.config = { ...mount.config, ...saved.config };
      }
      if (request.method() === 'POST') {
        const body = request.postDataJSON();
        if (body.action === 'aliyunBrowse') {
          browses.push(body);
          const directories = body.parentId === 'root'
            ? [{ id: body.config.drive_type === 'backup' ? 'backup-folder' : 'photos', name: body.config.drive_type === 'backup' ? 'Archive' : 'Photos' }]
            : body.parentId === 'photos' ? [{ id: 'year', name: '2026' }] : [];
          data = { directories };
        } else if (body.action === 'fileList') {
          data = cloudFiles[body.path] || [];
        } else if (body.action === 'fileTask') {
          data = { state: 2, progress: 100 };
        } else {
          assert.ok(['fileRename', 'fileMove'].includes(body.action));
          operations.push(body);
          const parent = path.posix.dirname(body.path);
          const name = path.posix.basename(body.path);
          const index = cloudFiles[parent].findIndex(item => item.name === name);
          assert.notEqual(index, -1);
          if (body.action === 'fileRename') cloudFiles[parent][index].name = body.name;
          else {
            const [entry] = cloudFiles[parent].splice(index, 1);
            cloudFiles[path.posix.dirname(body.destination)].push(entry);
          }
          data = { taskId: 'cloud-task' };
        }
      }
      await route.fulfill({ json: { code: 200, data } });
    });
    try {
      await page.goto(server.url + '/#/engine');
      await page.getByRole('button', { name: '目录管理', exact: true }).waitFor();
      assert.equal(await page.getByRole('button', { name: '并行复制数', exact: true }).count(), 0);
      await page.getByRole('button', { name: '目录管理', exact: true }).click();
      const cloudRow = page.locator('.mount-item').filter({ has: page.locator('strong', { hasText: /^Cloud$/ }) });
      const archiveRow = page.locator('.mount-item').filter({ has: page.locator('strong', { hasText: /^Archive$/ }) });
      await cloudRow.getByRole('button', { name: '并行复制数', exact: true }).click();
      const settings = page.getByRole('dialog', { name: '并行复制数：Cloud', exact: true });
      assert.equal(await settings.getByRole('spinbutton').inputValue(), '5');
      await settings.getByRole('spinbutton').fill('8');
      await settings.getByRole('button', { name: '确定', exact: true }).click();
      await settings.waitFor({ state: 'hidden' });
      await cloudRow.getByRole('button', { name: '并行复制数', exact: true }).click();
      assert.equal(await settings.getByRole('spinbutton').inputValue(), '8');
      assert.equal(cloud.copyConcurrency, 8);
      assert.equal(archive.copyConcurrency, 2);
      await archiveRow.getByText('并行 2', { exact: true }).waitFor();
      await waitForDialogs(page);
      await page.screenshot({ path: path.join(output, 'concurrency-' + (mobile ? 'mobile' : 'desktop') + '.png') });
      await settings.getByRole('button', { name: '取消', exact: true }).click();
      await waitForDialogs(page);
      await page.screenshot({ path: path.join(output, 'directories-' + (mobile ? 'mobile' : 'desktop') + '.png') });
      await cloudRow.getByRole('button', { name: '云端文件', exact: true }).click();
      const fileDialog = page.getByRole('dialog', { name: '云端文件：Cloud', exact: true });
      const fileRow = fileDialog.getByRole('row').filter({ hasText: 'report.txt' });
      await fileRow.getByRole('button', { name: '重命名', exact: true }).click();
      const renameDialog = page.locator('.el-message-box');
      await renameDialog.locator('input').fill('/invalid');
      await renameDialog.getByRole('button', { name: '确定', exact: true }).click();
      await renameDialog.getByText('名称不能为空，不能包含斜杠或控制字符', { exact: true }).waitFor();
      assert.equal(operations.length, 0);
      await renameDialog.locator('input').fill('renamed.txt');
      await renameDialog.getByRole('button', { name: '确定', exact: true }).click();
      const renamedRow = fileDialog.getByRole('row').filter({ hasText: 'renamed.txt' });
      await renamedRow.waitFor();
      await renamedRow.getByRole('button', { name: '移动', exact: true }).click();
      const moveDialog = page.getByRole('dialog', { name: '移动', exact: true });
      await moveDialog.locator('.el-select').click();
      const cloudRoot = page.locator('.el-select-dropdown:visible .el-tree-node__content').filter({ hasText: /^Cloud$/ });
      await cloudRoot.locator('.el-tree-node__expand-icon').click();
      await page.locator('.el-select-dropdown:visible').getByText('ArchiveFolder', { exact: true }).click();
      await waitForDialogs(page);
      await page.waitForFunction(() => !document.querySelector('.el-message'));
      await page.screenshot({ path: path.join(output, 'cloud-move-' + (mobile ? 'mobile' : 'desktop') + '.png') });
      await moveDialog.getByRole('button', { name: '确定', exact: true }).click();
      await moveDialog.waitFor({ state: 'hidden' });
      await renamedRow.waitFor({ state: 'hidden' });
      await fileDialog.getByRole('button', { name: 'ArchiveFolder', exact: true }).click();
      await renamedRow.waitFor();
      assert.equal(operations[0].path, '/Cloud/report.txt');
      assert.equal(operations[0].name, 'renamed.txt');
      assert.equal(operations[1].destination, '/Cloud/ArchiveFolder/renamed.txt');
      await waitForDialogs(page);
      await page.waitForFunction(() => !document.querySelector('.el-message'));
      const actionBoxes = await renamedRow.locator('.cloud-file-actions button').evaluateAll(buttons =>
        buttons.map(button => { const { x, y, width } = button.getBoundingClientRect(); return { x, y, width }; }));
      assert.equal(actionBoxes.length, 2);
      assert.equal(actionBoxes[0].y, actionBoxes[1].y);
      assert.ok(actionBoxes[0].x + actionBoxes[0].width <= actionBoxes[1].x);
      await page.screenshot({ path: path.join(output, 'cloud-files-' + (mobile ? 'mobile' : 'desktop') + '.png') });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await fileDialog.locator('.el-dialog__headerbtn').click();
      await cloudRow.getByRole('button', { name: '编辑', exact: true }).click();
      const form = page.locator('.mount-editor-dialog');
      const rapidUpload = form.getByRole('switch');
      assert.equal(await rapidUpload.getAttribute('aria-checked'), 'true');
      const threshold = form.getByRole('spinbutton', { name: '秒传条件（文件大小严格大于此 MB 数）' });
      assert.equal(await threshold.inputValue(), '10');
      await threshold.fill('32');
      await threshold.press('Tab');
      const concurrency = form.locator('.el-form-item').filter({ has: page.locator('.el-form-item__label', { hasText: /^并行复制数$/ }) });
      assert.equal(await concurrency.getByRole('spinbutton').inputValue(), '8');
      await form.locator('.el-switch').click();
      assert.equal(await rapidUpload.getAttribute('aria-checked'), 'false');
      assert.equal(await threshold.count(), 0);
      assert.equal(await form.getByText('根文件夹 ID', { exact: true }).count(), 0);
      const root = form.locator('.el-form-item').filter({ has: page.locator('.el-form-item__label', { hasText: '根文件夹' }) });
      const picker = page.getByRole('dialog', {name: '选择目录', exact: true});
      await root.getByRole('button', {name: '选择目录'}).click();
      const photos = picker.locator('.el-tree-node__content').filter({ hasText: 'Photos' });
      await photos.locator('.el-tree-node__expand-icon').click();
      await picker.getByText('2026', { exact: true }).click();
      await picker.getByRole('button', {name: '确定', exact: true}).click();
      await picker.waitFor({ state: 'hidden' });
      assert.equal(browses[0].engineId, 1);
      assert.equal(browses[0].mountId, 11);
      await waitForDialogs(page);
      await page.screenshot({ path: path.join(output, 'root-folder-' + (mobile ? 'mobile' : 'desktop') + '.png') });
      await form.getByRole('button', { name: '确定', exact: true }).click();
      await form.waitFor({ state: 'hidden' });
      assert.equal(saved.config.root_folder_id, 'year');
      assert.equal(saved.config.root_folder_path, '/Photos/2026');
      assert.equal(saved.config.rapid_upload, false);
      assert.equal(saved.config.rapid_upload_min_mb, 32);
      assert.equal(saved.copyConcurrency, 8);
      await cloudRow.getByText('资源库 /Photos/2026', { exact: true }).waitFor();
      await cloudRow.getByRole('button', { name: '编辑', exact: true }).click();
      assert.equal(await rapidUpload.getAttribute('aria-checked'), 'false');
      assert.equal(await threshold.count(), 0);
      await form.locator('.el-switch').click();
      assert.equal(await threshold.inputValue(), '32');
      const space = form.locator('.el-form-item').filter({ has: page.locator('.el-form-item__label', { hasText: '网盘空间' }) });
      await space.locator('.el-select').click();
      await page.getByRole('option', { name: '备份盘', exact: true }).click();
      await root.getByRole('button', {name: '选择目录'}).click();
      await picker.getByText('Archive', { exact: true }).waitFor();
      await picker.getByRole('button', {name: '取消', exact: true}).click();
      assert.equal(browses.at(-1).config.drive_type, 'backup');
      assert.equal(browses.at(-1).config.root_folder_id, 'root');
      assert.equal(await page.getByText('Photos', { exact: true }).count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await form.getByRole('button', { name: '取消', exact: true }).click();
      cloud.config = { ...cloud.config, auth_mode: undefined, auth_service_url: 'https://auth.example.test', root_folder_id: 'legacy-folder', root_folder_path: undefined };
      await page.reload();
      await page.getByRole('button', { name: '目录管理', exact: true }).click();
      await cloudRow.getByRole('button', { name: '编辑', exact: true }).click();
      assert.equal(await form.getByText('legacy-folder', { exact: true }).count(), 0);
      await form.getByRole('button', { name: '确定', exact: true }).click();
      await form.waitFor({ state: 'hidden' });
      assert.equal(saved.config.root_folder_id, 'legacy-folder');
      assert.deepEqual(state.errors, []);
      console.log((mobile ? 'mobile' : 'desktop') + ': per-directory concurrency, rapid upload, cloud rename/move, folder selection passed');
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
  await server.close();
}
