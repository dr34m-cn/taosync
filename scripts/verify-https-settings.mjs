import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createDemoServer, preparePage } from './readme-screenshots.mjs';

const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const browser = await chromium.launch({ channel: 'msedge' });
const demo = await createDemoServer();
try {
  for (const mobile of [false, true]) {
    const language = mobile ? 'en' : 'zh-CN';
    const { context, page, errors } = await preparePage(browser, demo.url, mobile, language);
    const state = { enabled: false, configured: false, autoStart: false, port: 8025 };
    const writes = [];
    let deletes = 0;
    await context.route('**/svr/settings', route => route.fulfill({ json: { code: 200, data: {} } }));
    await context.route('**/svr/settings/update', route => route.fulfill({ json: { code: 200, data: { supported: false } } }));
    await context.route('**/svr/settings/https', route => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON();
        writes.push(body);
        if (writes.length === 1) return route.fulfill({ json: { code: 500, msg: 'Test validation error' } });
        Object.assign(state, { enabled: body.enabled, autoStart: body.enabled, configured: true });
      } else if (route.request().method() === 'DELETE') {
        deletes++;
        Object.assign(state, { enabled: false, autoStart: false, configured: false });
      }
      return route.fulfill({ json: { code: 200, data: state } });
    });
    await page.goto(demo.url + '/#/setting');
    const https = page.getByRole('region', { name: 'HTTPS', exact: true });
    const toggle = https.getByRole('switch');
    const clickSwitch = () => https.locator('.el-switch').click();
    const cert = https.getByRole('group', { name: mobile ? 'Certificate chain (PEM)' : '证书链（PEM）', exact: true });
    const key = https.getByRole('group', { name: mobile ? 'Unencrypted private key (PEM)' : '无密码私钥（PEM）', exact: true });
    const save = https.getByRole('button', { name: mobile ? 'Save and Apply' : '保存并生效' });
    const clearLabel = mobile ? 'Clear certificate' : '清空证书';
    const clear = https.getByRole('button', { name: clearLabel });
    await clickSwitch();
    const [left, right] = await Promise.all([cert.boundingBox(), key.boundingBox()]);
    assert.ok(mobile ? right.y >= left.y + left.height : right.x >= left.x + left.width);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    const chooser = page.waitForEvent('filechooser');
    await cert.locator('.el-upload').press('Enter');
    await (await chooser).setFiles({ name: 'first.crt', mimeType: 'text/plain', buffer: Buffer.from('first') });
    await cert.getByText('first.crt', { exact: true }).waitFor();
    await cert.locator('.el-upload-dragger').evaluate(el => {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(new File(['replacement cert'], 'replacement.pem'));
      el.dispatchEvent(new DragEvent('drop', { dataTransfer, bubbles: true, cancelable: true }));
    });
    await cert.getByText('replacement.pem', { exact: true }).waitFor();
    assert.equal(await save.isDisabled(), true);
    await key.getByText(mobile ? 'Enter text' : '手动填写', { exact: true }).click();
    const text = key.getByRole('textbox');
    await text.fill('界'.repeat(90000));
    await key.getByRole('alert').waitFor();
    assert.equal(await save.isDisabled(), true);
    await text.fill('draft key\nsecond line');
    assert.equal(writes.length, 0);
    await save.click();
    await page.getByText('Test validation error', { exact: true }).waitFor();
    assert.deepEqual(writes[0], { enabled: true, certificate: 'replacement cert', privateKey: 'draft key\nsecond line' });
    assert.equal(await text.inputValue(), writes[0].privateKey);
    await save.click();
    await https.getByRole('link').waitFor();
    await clickSwitch();
    await save.click();
    await save.waitFor({ state: 'hidden' });
    assert.deepEqual(writes[2], { enabled: false });
    await page.reload();
    await clear.waitFor();
    assert.equal(await toggle.isChecked(), false);
    await clickSwitch();
    await save.click();
    await https.getByRole('link').waitFor();
    assert.deepEqual(writes[3], { enabled: true });
    const dialog = page.getByRole('dialog', { name: clearLabel });
    await clear.click();
    await dialog.getByRole('button', { name: mobile ? 'Cancel' : '取消' }).click();
    await dialog.waitFor({ state: 'hidden' });
    assert.equal(deletes, 0);
    await clear.click();
    await dialog.getByRole('button', { name: clearLabel }).click();
    await clear.waitFor({ state: 'hidden' });
    assert.equal(deletes, 1);
    assert.equal(await toggle.isChecked(), false);
    await clickSwitch();
    assert.equal(await save.isDisabled(), true);
    assert.deepEqual(errors, []);
    await context.close();
    console.log(`${language}: file chooser, drag and drop, manual entry, retry, retain, reuse and clear passed`);
  }
} finally {
  await browser.close();
  await demo.close();
}
