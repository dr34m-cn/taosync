// Build web first. Uses the same optional Playwright installation as scripts/verify-engine-transfer.mjs.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import process from 'node:process';
import { createDemoServer, preparePage } from '../../scripts/readme-screenshots.mjs';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const browser = await chromium.launch(process.env.SCREENSHOT_BROWSER_EXECUTABLE
  ? { executablePath: process.env.SCREENSHOT_BROWSER_EXECUTABLE } : { channel: 'msedge' });
const server = await createDemoServer();
try {
  const { page, context, errors } = await preparePage(browser, server.url, false);
  const engine = { id: 1, engineType: 'taosync', displayName: 'TaoSync' };
  const mounts = [
    { id: 2, engineId: 1, driverType: 'local', name: 'Archive', config: { root_path: '/media' } },
    { id: 3, engineId: 1, driverType: 'smb', name: 'NAS', config: {} },
    { id: 4, engineId: 1, driverType: 'crypt', name: 'Vault', config: {} },
    { id: 5, engineId: 2, driverType: 'local', name: 'Other engine', config: {} },
  ];
  const browses = [];
  const writes = [];
  const key = ' test-only recovery key ';
  const reply = (route, data) => route.fulfill({ json: { code: 200, data } });
  await context.route('**/svr/alist*', route => {
    const params = new URL(route.request().url()).searchParams;
    if (!params.has('path')) return reply(route, [engine]);
    browses.push(Object.fromEntries(params));
    return reply(route, params.get('path') === '/Archive/' ? [{ path: '备份' }] : [{ path: '2026' }]);
  });
  await context.route('**/svr/storage*', route => {
    if (route.request().method() === 'GET') return reply(route, mounts);
    const body = route.request().postDataJSON();
    writes.push(body);
    if (route.request().method() === 'POST') {
      const config = { ...body.config };
      delete config.encryption_key;
      mounts.push({ ...body, id: 10 + writes.length, config });
    }
    return reply(route, null);
  });
  await page.goto(server.url + '/#/engine');
  const button = (scope, name) => scope.getByRole('button', { name, exact: true });
  await button(page, '目录管理').click();
  const form = page.locator('.mount-editor-dialog');
  const field = label => form.locator('.el-form-item').filter({ has: page.locator('.el-form-item__label', { hasText: label }) });
  const option = name => page.getByRole('option', { name, exact: true });
  const save = async () => { await button(form, '确定').click(); await form.waitFor({ state: 'hidden' }); };
  async function newCrypt(name) {
    await button(page, '添加目录').click();
    assert.equal(await field('加密密钥').count(), 0);
    await field('目录名称').locator('input').fill(name);
    await field('网盘类型').locator('.el-select').click();
    await option('加密目录').click();
    await form.getByText(/专用根目录.*明文.*备份密钥/).waitFor();
    await form.locator('.el-alert--warning + .el-alert--error').getByText('务必妥善保管秘钥，一旦秘钥和本程序数据库都丢失，您将永远失去被加密的文件', { exact: true }).waitFor();
  }
  async function chooseMount(name) {
    const select = field('目标挂载');
    await select.locator('.el-select').click();
    const list = page.locator(`[id="${await select.getByRole('combobox').getAttribute('aria-controls')}"]`);
    assert.deepEqual(await list.getByRole('option').allTextContents(), ['Archive', 'NAS']);
    await list.getByRole('option', { name, exact: true }).click();
  }
  async function selectNestedFolder() {
    await field('目标文件夹').locator('.el-select').click();
    const tree = page.locator('.el-select-dropdown:visible');
    const row = text => tree.locator('.el-tree-node__content').filter({ has: page.getByText(text, { exact: true }) });
    await row('/').locator('.el-tree-node__expand-icon').click();
    await row('/备份').locator('.el-tree-node__expand-icon').click();
    await row('/备份/2026').click();
    await tree.waitFor({ state: 'hidden' });
  }

  await newCrypt('Child vault');
  await button(form, '确定').click();
  await field('目标挂载').locator('.el-form-item__error').waitFor();
  await field('加密密钥').locator('.el-form-item__error').waitFor();
  await chooseMount('Archive');
  await field('加密密钥').locator('input').fill('   ');
  await button(form, '确定').click();
  await field('加密密钥').locator('.el-form-item__error').waitFor();
  assert.equal(writes.length, 0);
  await field('加密密钥').locator('input').fill(key);
  await selectNestedFolder();
  assert.deepEqual(browses, [{ alistId: '1', path: '/Archive/' }, { alistId: '1', path: '/Archive/备份/' }]);
  await field('加密文件夹名称').locator('.el-switch').click();
  await save();
  assert.deepEqual(writes[0], { engineId: 1, driverType: 'crypt', name: 'Child vault', copyConcurrency: 5,
    config: { target_mount_id: 2, target_path: '/备份/2026', encryption_key: key, encrypt_dir_names: true } });

  const row = page.locator('.mount-item').filter({ hasText: 'Child vault' });
  await button(row, '编辑').click();
  for (const label of ['网盘类型', '目标挂载', '目标文件夹', '加密密钥', '加密文件夹名称']) {
    assert.ok(await field(label).locator('input').isDisabled());
  }
  assert.equal(await field('加密密钥').locator('input').inputValue(), '');
  assert.equal(await field('目标文件夹').locator('input').inputValue(), '/备份/2026');
  await field('目标文件夹').hover();
  await page.getByRole('tooltip').filter({ hasText: '不可更改' }).waitFor();
  await field('并行复制数').getByRole('spinbutton').fill('7');
  await save();
  assert.deepEqual(writes[1], { id: 11, copyConcurrency: 7 });

  await newCrypt('Root vault');
  await chooseMount('Archive');
  await selectNestedFolder();
  await chooseMount('NAS');
  await field('加密密钥').locator('input').fill(key);
  await save();
  assert.deepEqual(writes[2].config, { target_mount_id: 3, target_path: '/', encryption_key: key, encrypt_dir_names: false });
  assert.deepEqual(errors, []);
  console.log('Encrypted directory creation, validation, target browsing, saved locks and concurrency passed.');
} finally {
  await browser.close();
  await server.close();
}
