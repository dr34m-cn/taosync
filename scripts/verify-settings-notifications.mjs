import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { preparePage } from './readme-screenshots.mjs';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const frontendUrl = process.env.TAO_VERIFY_FRONTEND_URL || 'http://localhost:18023';
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const output = path.resolve('build/verification/settings-notifications');
await mkdir(output, { recursive: true });

try {
  for (const mobile of [false, true]) {
    const { context, page, errors } = await preparePage(browser, frontendUrl, mobile);
    const settings = { task_save: 0, timeout: 72, source_full_scan_days: 15, aliyun_auth_server: 'https://auth.example' };
    const writes = [];
    const uploads = [];
    const notices = [];
    const testNotices = [];
    let rejected = false;
    let renamed = false;
    await context.route('**/svr/settings/update', route => route.fulfill({ json: { code: 200, data: {
      supported: true, pinned: false, target: 'windows-amd64', architecture: 'AMD64', maxBytes: 32,
    } } }));
    await context.route('**/svr/settings/update/upload', route => {
      uploads.push(route.request());
      return route.fulfill({ status: 400, json: { msg: '模拟校验未通过' } });
    });
    await context.route('**/svr/settings', async route => {
      if (route.request().method() === 'PUT') {
        const { settings: changed } = route.request().postDataJSON();
        if (changed.timeout === 1) {
          rejected = true;
          return route.fulfill({ json: { code: 500, msg: 'Test disk write failure' } });
        }
        Object.assign(settings, changed);
        writes.push(changed);
      }
      await route.fulfill({ json: { code: 200, data: settings } });
    });
    await context.route('**/svr/user', async route => {
      if (route.request().method() !== 'PUT') return route.fallback();
      const { userName } = route.request().postDataJSON();
      renamed = true;
      await route.fulfill({ json: { code: 200, data: { id: 1, userName, createTime: 1800000000 } } });
    });
    await context.route('**/svr/notify', async route => {
      const method = route.request().method();
      if (method === 'POST') {
        const { notify } = route.request().postDataJSON();
        if (Object.hasOwn(notify, 'enable')) notices.push({ ...notify, id: notices.length + 1 });
        else {
          assert.ok([5, 6, 7, 8].includes(notify.method));
          testNotices.push(notify);
        }
      } else if (method === 'PUT') {
        const { notify } = route.request().postDataJSON();
        notices[notices.findIndex(item => item.id === notify.id)] = notify;
      }
      await route.fulfill({ json: { code: 200, data: notices } });
    });
    const noOverflow = async () => {
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
      assert.equal(overflow, false, 'Page must fit the viewport');
    };
    const waitFor = async predicate => {
      const deadline = Date.now() + 5000;
      while (!predicate() && Date.now() < deadline) await page.waitForTimeout(25);
      assert.ok(predicate());
    };
    const capture = async name => {
      await page.evaluate(() => document.fonts.ready);
      await page.waitForFunction(() => document.querySelectorAll('.el-message').length === 0);
      await page.screenshot({ path: path.join(output, `${mobile ? 'mobile' : 'desktop'}-${name}.png`), animations: 'disabled' });
    };
    try {
      await page.goto(frontendUrl + '/#/setting');
      await page.getByRole('spinbutton', { name: '源目录完整比对周期' }).waitFor();
      assert.equal(await page.locator('.setting input[type=password]').count(), 0);
      const retention = page.getByRole('spinbutton', { name: '任务记录保留时间' });
      const rows = await page.locator('.settings-fields .el-form-item').evaluateAll((items, mobile) => items.map(item => {
        const label = item.querySelector('label').getBoundingClientRect();
        const input = item.querySelector('input').getBoundingClientRect();
        if (mobile ? label.bottom > input.top : label.right > input.left) return null;
        return Math.round(input.top);
      }), mobile);
      assert.equal(rows.length, 4);
      assert.ok(rows.every(top => top !== null));
      assert.equal(new Set(rows).size, 4);

      for (const title of ['https-heading', 'api-key-general', 'api-key-execute']) {
        const header = page.locator(`section[aria-labelledby="${title}"] header`);
        await header.locator('.el-switch').waitFor();
        const centers = await header.locator('h2, button, .el-switch, .controls > span').evaluateAll(items => items.map(item => {
          const box = item.getBoundingClientRect();
          return box.top + box.height / 2;
        }));
        assert.ok(Math.max(...centers) - Math.min(...centers) <= 1, `${title} controls must align with the heading`);
      }
      const update = page.getByRole('region', { name: '程序更新' });
      const registry = update.getByRole('link', { name: '授信清单', exact: true });
      assert.equal(await registry.getAttribute('href'), 'https://taoapi.dr34m.cn/');
      assert.match(await registry.locator('..').innerText(), /允许安装授信清单中/);
      assert.equal(await update.getByRole('link', { name: 'GitHub Releases' }).getAttribute('href'), 'https://github.com/dr34m-cn/taosync/releases');
      const install = update.getByRole('button', { name: '更新并重启' });
      const drop = name => update.locator('.el-upload-dragger').evaluate((el, name) => {
        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(new File(['drop'], name));
        el.dispatchEvent(new DragEvent('drop', { dataTransfer, bubbles: true, cancelable: true }));
      }, name);
      const chooser = page.waitForEvent('filechooser');
      await update.getByText('点击选择').click();
      await (await chooser).setFiles({ name: 'release.zip', mimeType: 'application/zip', buffer: Buffer.from('pick') });
      await update.getByText('release.zip', { exact: true }).waitFor();
      await drop('release.tar.gz');
      await update.getByText('release.tar.gz', { exact: true }).waitFor();
      await update.getByText('release.zip', { exact: true }).waitFor({ state: 'detached' });
      for (const size of [0, 33]) {
        await update.locator('input[type=file]').setInputFiles({ name: 'invalid.exe', mimeType: 'application/octet-stream', buffer: Buffer.alloc(size) });
        await update.getByText(/请选择非空/).waitFor();
        assert.equal(await install.isDisabled(), true);
      }
      await drop('taoSync');
      await install.click();
      const confirm = page.getByRole('dialog', { name: '确认更新程序' });
      await confirm.getByRole('button', { name: '取消' }).click();
      assert.equal(uploads.length, 0);
      await install.click();
      await confirm.getByRole('button', { name: '更新并重启' }).click();
      await update.getByText('模拟校验未通过').waitFor();
      assert.equal(uploads.length, 1);
      assert.equal(uploads[0].headers()['x-taosync-release'], undefined);
      assert.equal(uploads[0].postDataBuffer().toString(), 'drop');
      await retention.fill('7');
      await retention.press('Tab');
      const timeout = page.getByRole('spinbutton', { name: '任务执行超时' });
      await timeout.fill('1');
      await timeout.press('Tab');
      assert.equal(writes.length, 0);
      assert.equal(rejected, false);
      assert.equal(settings.task_save, 0);
      assert.equal(await page.locator('.setting .el-input-number__increase, .setting .el-input-number__decrease').count(), 0);
      const saveSettings = page.getByRole('region', { name: '同步配置' }).getByRole('button', { name: '保存并生效', exact: true });
      await saveSettings.click();
      await waitFor(() => rejected);
      await page.waitForFunction(() => !document.querySelector('.setting input').disabled);
      assert.equal(await timeout.inputValue(), '1');
      assert.equal(await retention.inputValue(), '7');
      assert.equal(settings.timeout, 72);
      await timeout.fill('24');
      await page.getByRole('spinbutton', { name: '源目录完整比对周期' }).fill('16');
      await page.getByRole('textbox', { name: '阿里云盘授权服务地址' }).fill('https://settings.example');
      await saveSettings.click();
      await waitFor(() => writes.length === 1);
      assert.deepEqual(writes[0], { task_save: 7, timeout: 24, source_full_scan_days: 16, aliyun_auth_server: 'https://settings.example' });
      await page.reload();
      await page.getByRole('spinbutton', { name: '任务记录保留时间' }).waitFor();
      assert.equal(await retention.inputValue(), '7');
      assert.equal(await timeout.inputValue(), '24');
      assert.equal(await page.getByRole('spinbutton', { name: '源目录完整比对周期' }).inputValue(), '16');
      assert.equal(await page.getByRole('textbox', { name: '阿里云盘授权服务地址' }).inputValue(), 'https://settings.example');
      await noOverflow();
      await capture('settings');

      await page.locator('.header-user').click();
      await page.getByText('修改用户名', { exact: true }).click();
      const dialog = page.getByRole('dialog');
      await dialog.getByPlaceholder('请输入用户名').fill('新用户名');
      await capture('username');
      await dialog.getByRole('button', { name: '确定', exact: true }).click();
      await waitFor(() => renamed);
      await page.waitForFunction(() => window.$store.user.userName === '新用户名');
      await page.getByRole('dialog').waitFor({ state: 'hidden' });
      assert.equal(await page.locator('.account-info').getByText('用户名: 新用户名', { exact: true }).count(), 1);

      await page.goto(frontendUrl + '/#/notify');
      await page.locator('.card-add').click();
      await dialog.locator('.notify-method-form-item .el-select').click();
      await page.getByRole('option', { name: '高级自定义', exact: true }).click();
      await dialog.locator('.el-form-item').filter({ has: page.locator('label', { hasText: /^请求地址$/ }) }).locator('input').fill('https://notify.example/$title');
      await dialog.getByPlaceholder(/^Authorization:/).fill('Authorization: Bearer test');
      await noOverflow();
      await capture('advanced');
      await dialog.getByRole('button', { name: '测试', exact: true }).click();
      await page.getByText('测试消息已发送，请检查是否正确收到通知', { exact: true }).waitFor();
      await dialog.getByRole('button', { name: '确定', exact: true }).click();
      await waitFor(() => notices.length === 1);
      assert.equal(notices[0].method, 5);
      assert.equal(JSON.parse(notices[0].params).headers, 'Authorization: Bearer test');
      await page.getByRole('dialog').waitFor({ state: 'hidden' });
      await page.locator('.card-item').filter({ hasText: '高级自定义' }).getByRole('button', { name: '编辑' }).click();
      assert.equal(await dialog.getByPlaceholder(/^Authorization:/).inputValue(), 'Authorization: Bearer test');
      await dialog.getByRole('button', { name: '取消', exact: true }).click();

      await page.locator('.card-add').click();
      await dialog.locator('.notify-method-form-item .el-select').click();
      await page.getByRole('option', { name: 'Bark', exact: true }).click();
      await dialog.getByPlaceholder('https://api.day.app/device_key').fill('test-device-key');
      await noOverflow();
      await capture('bark');
      await dialog.getByRole('button', { name: '确定', exact: true }).click();
      await waitFor(() => notices.length === 2);
      assert.equal(notices[1].method, 6);
      assert.equal(JSON.parse(notices[1].params).push, 'test-device-key');
      await dialog.waitFor({ state: 'hidden' });

      for (const provider of [
        { name: 'pushPlus', method: 7, key: 'token', placeholder: 'Token' },
        { name: 'PushDeer', method: 8, key: 'pushkey', placeholder: 'PushKey' },
      ]) {
        await page.locator('.card-add').click();
        await dialog.locator('.notify-method-form-item .el-select').click();
        await page.getByRole('option', { name: provider.name, exact: true }).click();
        const previousTests = testNotices.length;
        await dialog.getByRole('button', { name: '测试', exact: true }).click();
        await dialog.locator('.is-error').waitFor();
        assert.equal(testNotices.length, previousTests);
        await dialog.getByPlaceholder(provider.placeholder, { exact: true }).fill('test-provider-key');
        if (provider.method === 7) {
          await dialog.getByLabel('群组编码', { exact: true }).fill('test-group');
          await dialog.locator('.el-form-item').filter({ has: page.locator('label', { hasText: /^消息模板$/ }) }).locator('.el-select').click();
          await page.getByRole('option', { name: 'markdown', exact: true }).click();
        } else {
          await dialog.getByPlaceholder('https://api2.pushdeer.com/message/push').fill('https://deer.example/message/push');
        }
        await noOverflow();
        await capture(provider.name.toLowerCase());
        await dialog.getByRole('button', { name: '测试', exact: true }).click();
        await waitFor(() => testNotices.length === previousTests + 1);
        assert.equal(testNotices.at(-1).method, provider.method);
        const count = notices.length;
        await dialog.getByRole('button', { name: '确定', exact: true }).click();
        await waitFor(() => notices.length === count + 1);
        assert.equal(notices.at(-1).method, provider.method);
        assert.equal(JSON.parse(notices.at(-1).params)[provider.key], 'test-provider-key');
        await dialog.waitFor({ state: 'hidden' });
        await page.locator('.card-item').filter({ has: page.getByText(provider.name, { exact: true }) }).getByRole('button', { name: '编辑' }).click();
        assert.equal(await dialog.getByPlaceholder(provider.placeholder, { exact: true }).inputValue(), 'test-provider-key');
        await dialog.getByPlaceholder(provider.placeholder, { exact: true }).fill('edited-provider-key');
        await dialog.getByRole('button', { name: '确定', exact: true }).click();
        await waitFor(() => JSON.parse(notices.at(-1).params)[provider.key] === 'edited-provider-key');
        await dialog.waitFor({ state: 'hidden' });
        await page.reload();
        await page.locator('.card-item').filter({ has: page.getByText(provider.name, { exact: true }) }).waitFor();
        await noOverflow();
      }
      assert.deepEqual(errors, []);
      console.log(`${mobile ? 'mobile' : 'desktop'}: explicit save, failed-save retry, rename, advanced webhook, Bark, pushPlus and PushDeer passed`);
    } catch (error) {
      await page.screenshot({ path: path.join(output, `${mobile ? 'mobile' : 'desktop'}-failure.png`) });
      console.error((await page.locator('body').innerText()).slice(0, 4000));
      throw error;
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
}
