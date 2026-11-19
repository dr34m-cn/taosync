// Run against a freshly built web/dist with the optional Playwright setup used by the other UI checks.
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
  for (const mobile of [false, true]) {
    const { page, context, errors } = await preparePage(browser, server.url, mobile);
    const writes = [];
    await context.route('**/svr/alist*', route => {
      const req = route.request();
      const parent = new URL(req.url()).searchParams.get('path');
      if (req.method() === 'GET' && !parent) return route.fallback();
      if (req.method() === 'POST') {
        const body = req.postDataJSON();
        writes.push(body);
        if (body.name === 'existing') return route.fulfill({ json: { code: 500, msg: '同名目录' } });
        return route.fulfill({ json: { code: 200, data: body.parent + body.name + '/' } });
      }
      const names = parent === '/' ? ['Archive', 'Photos'] : parent === '/Archive/' ? ['existing'] : [];
      return route.fulfill({ json: { code: 200, data: names.map(path => ({ path })) } });
    });
    await page.goto(server.url + '/#/home');
    const button = (scope, name) => scope.getByRole('button', { name, exact: true });
    await button(page, '新建作业').click();
    const editor = page.locator('.el-dialog:visible, .el-drawer:visible').last();
    await editor.locator('.el-form-item').filter({ has: page.locator('.el-form-item__label', { hasText: '引擎' }) }).locator('.el-select').click();
    await page.getByRole('option').filter({ hasText: mobile ? 'TaoSync' : '192.168.1.20' }).first().click();
    const picker = page.getByRole('dialog', { name: '选择目录', exact: true });
    const prompt = page.getByRole('dialog', { name: '新建目录', exact: true });
    for (const [index, directory] of ['Photos', 'Archive'].entries()) {
      await button(editor, '选择选择目录').first().click();
      const root = picker.locator('.el-tree-node__content').filter({ has: page.getByText('根目录', { exact: true }) });
      await root.waitFor();
      assert.equal(await button(root, '新建目录').count(), 0);
      const row = picker.locator('.el-tree-node__content').filter({ has: page.getByText(directory, { exact: true }) });
      await button(row, '新建目录').click();
      const input = prompt.getByRole('textbox');
      if (index === 1) {
        await input.fill('../bad');
        await button(prompt, '确定').click();
        await prompt.getByText('请输入单个有效的目录名').waitFor();
        assert.equal(writes.length, 1);
        await input.fill('existing');
        await button(prompt, '确定').click();
        await page.getByText('同名目录', { exact: true }).waitFor();
      }
      const name = index === 0 ? '新源' : '新目标';
      const parent = `/${directory}/`;
      await input.fill(name);
      await button(prompt, '确定').click();
      await picker.locator('.is-current > .el-tree-node__content').getByText(name, { exact: true }).waitFor();
      await button(picker, '确定').click();
      await editor.locator('.el-form-item').filter({ hasText: parent + name + '/' }).waitFor();
      assert.deepEqual(writes.at(-1), { action: 'mkdir', alistId: mobile ? 1 : 2, parent, name });
    }
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log('Desktop and mobile source/target folder creation passed.');
} finally {
  await browser.close();
  await server.close();
}
