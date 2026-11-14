// Build first: npm --prefix web run build
// Run with Playwright installed: node scripts/readme-screenshots.mjs
// Optional: PLAYWRIGHT_MODULE_PATH and SCREENSHOT_BROWSER_EXECUTABLE.
import http from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'README', 'screenshots');
const time = (date) => Date.parse(`${date}+08:00`) / 1000;
const now = time('2026-11-14T10:28:00');
const GiB = 1024 ** 3;
const MiB = 1024 ** 2;
const user = { id: 1, userName: '桃桃爸爸', createTime: time('2026-01-01T09:00:00') };
const engines = [
  { id: 1, engineType: 'taosync', displayName: 'TaoSync', remark: '家庭数据中心', directoryCount: 5 },
  { id: 2, engineType: 'alist', userName: '家庭云盘', url: 'http://192.168.1.20:5244', remark: '家庭照片与旅行影像' },
  { id: 3, engineType: 'alist', userName: '工作资料库', url: 'http://192.168.1.30:5244', remark: '项目文档与设计素材' },
  { id: 4, engineType: 'alist', userName: '异地备份', url: 'https://家庭备份.example.com', remark: '每晚定时归档' },
];
const mounts = [
  { id: 11, name: '家庭相册', driverType: 'local', config: { root_path: 'D:\\家庭资料\\照片' } },
  { id: 12, name: '家庭备份', driverType: 'smb', config: { host: '192.168.1.10', port: 445, share: '家庭备份', root_path: '/相册', domain: '', username: '备份用户', password: '' }, secretState: { password: true } },
  { id: 13, name: '远程归档', driverType: 'sftp', config: { host: '192.168.1.50', port: 22, username: '归档用户', root_path: '/资料归档', timeout: 30, auth_type: 'password', password: '', host_key_fingerprint: '' }, secretState: { password: true } },
  { id: 14, name: '影像资料', driverType: 'ftp', config: { host: '192.168.1.60', port: 21, username: '影像管理员', root_path: '/旅行影像', passive: true, tls: true, password: '' }, secretState: { password: true } },
  { id: 15, name: '阿里云相册', driverType: 'aliyun', config: { auth_mode: 'service', auth_service_url: '', drive_type: 'resource', root_folder_id: 'root', remove_way: 'trash' }, secretState: { refresh_token: true, refresh_proof: true } },
];
const jobSpecs = [
  ['家庭相册备份', '/家庭相册/桃桃成长', '/家庭备份/桃桃成长:/阿里云相册/桃桃成长', 0, 1, 0],
  ['旅行影像归档', '/影像资料/秋日旅行', '/远程归档/旅行影像', 0, 1, 1],
  ['工作文档同步', '/工作资料/项目文档', '/家庭备份/工作文档', 1, 1, 0],
  ['摄影素材整理', '/影像资料/待整理', '/家庭备份/精选素材', 2, 1, 2],
  ['设计资料备份', '/设计资料/品牌视觉', '/异地备份/设计资料', 0, 1, 1],
  ['家庭录像归档', '/家庭相册/周末时光', '/家庭备份/家庭录像', 0, 1, 0],
  ['旧照片整理', '/家庭相册/旧时光', '/远程归档/旧照片', 0, 0, 2],
  ['学习资料同步', '/学习资料/阅读笔记', '/家庭备份/学习资料', 1, 1, 0],
];
const jobs = jobSpecs.map(([remark, srcPath, dstPath, method, enable, isCron], i) => ({
  id: i + 1, alistId: [2, 7].includes(i) ? 3 : i === 4 ? 4 : 1, remark, srcPath, dstPath, method, enable, isCron,
  sourceMode: 0, useCacheT: 1, scanIntervalT: 1, useCacheS: 0, scanIntervalS: 0,
  interval: i === 0 ? 60 : 1440, exclude: '临时文件/:*.缓存', minFileSize: 1024, maxFileSize: 8 * GiB,
  year: null, month: null, day: null, week: null, day_of_week: null, hour: '2', minute: '0', second: '0', start_date: null, end_date: null,
  createTime: now - 86400 * (24 - i),
  lastTask: { id: 208 - i, status: i === 0 ? 1 : i === 4 ? 3 : 2, allNum: 128 - i * 7, successNum: i === 0 ? 86 : i === 4 ? 97 : 128 - i * 7, failNum: i === 4 ? 3 : 0, otherNum: 0, duration: 76 + i * 35, createTime: now - 1800 - i * 3600 },
}));
Object.assign(jobs[0].lastTask, { duration: 780, createTime: now - 780 });
const names = ['秋日公园合影.jpg', '桃桃的生日愿望.mp4', '第一次骑自行车.mp4', '周末野餐时光.jpg', '幼儿园运动会.mp4', '海边的晚霞.jpg', '成长相册封面.jpg', '亲子阅读记录.pdf', '露营星空合影.jpg', '家庭旅行手账.pdf'];
const files = names.map((fileName, i) => ({
  id: 3001 + i, fileName, fileSize: [12, 628, 382, 8, 942, 16, 6, 4, 18, 9][i] * MiB,
  srcPath: `/家庭相册/桃桃成长/${fileName}`, dstPath: `/家庭备份/桃桃成长/${fileName}`,
  createTime: now - 780 + i * 8, status: [2, 1, 1, 2, 0, 2, 2, 7, 2, 2][i],
  type: 0, isPath: false, progress: i === 1 ? 68 : 42,
  errMsg: i === 7 ? '目标目录暂时不可用，请检查存储连接后重试' : '',
}));
const albums = ['周末公园', '秋日露营', '海边旅行', '亲子手工', '成长记录', '生日派对', '家庭聚餐', '运动时光'];
for (let i = 0; i < 118; i++) {
  const video = i % 5 === 0;
  const fileName = `${albums[i % albums.length]}_${String(i + 1).padStart(2, '0')}.${video ? 'mp4' : 'jpg'}`;
  files.push({
    id: 3011 + i, fileName, fileSize: (video ? 256 : 12) * MiB, type: 0, isPath: false,
    srcPath: `/家庭相册/桃桃成长/${fileName}`, dstPath: `/家庭备份/桃桃成长/${fileName}`,
    createTime: now - 700 + i * 4, status: i < 80 ? 2 : 0, progress: 0, errMsg: '',
  });
}
const tasks = Array.from({ length: 8 }, (_, i) => ({
  id: 208 - i, status: i === 0 ? 1 : i === 4 ? 3 : 2,
  allNum: i === 0 ? 128 : 42 + i * 11, successNum: i === 0 ? 86 : i === 4 ? 83 : 42 + i * 11,
  failNum: i === 4 ? 3 : 0, otherNum: 0, createTime: now - 780 - i * 86400,
}));
const notifications = [
  { id: 1, enable: 1, method: 1, params: JSON.stringify({ sendKey: '演示通知密钥', notSendNull: 1 }) },
  { id: 2, enable: 1, method: 2, params: JSON.stringify({ url: 'https://通知.example.com/家庭备份', notSendNull: 1 }) },
  { id: 3, enable: 0, method: 3, params: JSON.stringify({ corpid: '家庭资料中心', agentid: '备份助手', corpsecret: '演示密钥', touser: '相册管理员', notSendNull: 1 }) },
  { id: 4, enable: 1, method: 4, params: JSON.stringify({ url: 'https://通知.example.com/归档提醒', notSendNull: 1 }) },
  { id: 5, enable: 0, method: 0, params: JSON.stringify({ url: 'https://通知.example.com/同步消息', method: 'POST', contentType: 'application/json', titleName: '标题', contentName: '内容', needContent: true, notSendNull: 1 }) },
];

function paginate(list, params) {
  const start = (Number(params.get('pageNum') || 1) - 1) * Number(params.get('pageSize') || 10);
  return { dataList: list.slice(start, start + Number(params.get('pageSize') || 10)), count: list.length };
}

function mockData(url, body, tick) {
  const params = url.searchParams;
  if (url.pathname === '/svr/user') return user;
  if (url.pathname === '/svr/alist') {
    if (params.has('path')) {
      const names = params.get('path') === '/' ? mounts.map(x => x.name) : ['桃桃成长', '家庭旅行', '周末时光', '精选照片', '成长记录'];
      return names.map(name => ({ path: name, leaf: params.get('path').split('/').filter(Boolean).length >= 2 }));
    }
    return engines;
  }
  if (url.pathname === '/svr/notify') return notifications;
  if (url.pathname === '/svr/storage') {
    const action = params.get('action') || body?.action;
    if (action === 'localBrowse') return {
      path: 'D:\\家庭资料', parent: 'D:\\', roots: [{ name: '系统盘', path: 'C:\\' }, { name: '资料盘', path: 'D:\\' }],
      directories: ['照片', '旅行影像', '工作文档', '学习资料', '家庭录像', '设计素材'].map(name => ({ name, path: `D:\\家庭资料\\${name}` })),
    };
    if (action === 'smbDiscover') return [
      { name: '家庭存储中心', address: '192.168.1.10' }, { name: '客厅影音服务器', address: '192.168.1.20' }, { name: '书房工作站', address: '192.168.1.30' },
    ];
    if (action === 'smbShares') return ['家庭备份', '旅行影像', '工作资料', '公共文档'].map(name => ({ name, comment: `${name}共享目录` }));
    if (action === 'sftpTest') return { rootPath: '/资料归档', directories: [] };
    if (action === 'sftpBrowse') return { path: body.path, directories: ['家庭相册', '旅行影像', '工作文档'].map(name => ({ name, path: `${body.path}/${name}`, leaf: false })) };
    if (!action) return mounts;
  }
  if (url.pathname === '/svr/job') {
    if (params.has('taskId')) {
      let result = files;
      if (params.has('status')) result = result.filter(x => x.status === Number(params.get('status')));
      if (params.has('type')) result = result.filter(x => x.type === Number(params.get('type')));
      return paginate(result, params);
    }
    if (params.has('current')) {
      if (params.get('id') !== '1') return null;
      if (params.has('status')) return files.filter(x => x.status === Number(params.get('status')));
      // Each response advances equally in both viewports so transfer rates remain meaningful.
      return {
        id: 208, scanFinish: true, createTime: now - 780, firstSync: now - 768, duration: 780 + tick,
        num: { wait: 39, running: 2, success: 86, fail: 1, other: 0 },
        size: Object.fromEntries([['wait', 0], ['running', 1], ['success', 2], ['fail', 7], ['other', 4]].map(([key, status]) => [key, files.filter(x => x.status === status).reduce((sum, file) => sum + file.fileSize, 0)])),
        doingTask: files.filter(x => x.status === 1).map(file => ({ ...file, progress: Math.min(99, file.progress + tick) })),
      };
    }
    if (params.has('id')) return paginate(params.get('id') === '1' ? tasks : tasks.slice(1), params);
    return paginate(jobs, params);
  }
  throw new Error(`Unhandled demo request: ${url.pathname} ${url.search}`);
}

export async function createDemoServer() {
  const dist = path.join(root, 'web', 'dist');
  const version = (await readFile(path.join(root, 'version.txt'), 'utf8')).split(/\r?\n/)[0];
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml', '.jpg': 'image/jpeg', '.ttf': 'font/ttf' };
  const server = http.createServer(async (request, response) => {
    try {
      const relative = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
      const file = path.resolve(dist, `.${relative === '/' ? '/index.html' : relative}`);
      if (!file.startsWith(`${dist}${path.sep}`)) throw new Error('Invalid path');
      response.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
      const content = await readFile(file);
      // Release builds stamp this token in CI; serve the same version locally.
      response.end(path.extname(file) === '.js' ? content.toString('utf8').replaceAll('__version_placeholder__', version) : content);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { url: `http://127.0.0.1:${server.address().port}`, close: () => new Promise(resolve => server.close(resolve)) };
}

export async function preparePage(browser, url, mobile) {
  const context = await browser.newContext({
    viewport: mobile ? { width: 440, height: 956 } : { width: 1920, height: 1080 },
    deviceScaleFactor: mobile ? 3 : 1, isMobile: mobile, hasTouch: mobile,
    locale: 'zh-CN', timezoneId: 'Asia/Shanghai', colorScheme: 'light', reducedMotion: 'reduce',
  });
  await context.addInitScript(({ user }) => {
    localStorage.setItem('lang', 'zh-CN');
    localStorage.setItem('vueuse-color-scheme', 'light');
    localStorage.setItem('app', JSON.stringify({ user, login: null }));
  }, { user });
  const errors = [];
  let tick = 0;
  await context.route('**/*', async route => {
    const request = route.request();
    const target = new URL(request.url());
    if (target.origin !== url) {
      errors.push(`External request blocked: ${target.origin}`);
      return route.abort();
    }
    if (!target.pathname.startsWith('/svr/')) return route.continue();
    try {
      const body = request.method() === 'POST' ? request.postDataJSON() : null;
      const readOnlyAction = target.pathname === '/svr/storage' && ['smbShares', 'sftpTest', 'sftpBrowse'].includes(body?.action);
      assert.ok(request.method() === 'GET' || readOnlyAction, 'Screenshots must never submit mutations');
      if (target.searchParams.has('current') && !target.searchParams.has('status')) tick++;
      const data = mockData(target, body, tick);
      return route.fulfill({ json: { code: 200, msg: '操作成功', data } });
    } catch (error) {
      errors.push(error.message);
      return route.fulfill({ status: 500, json: { code: 500, msg: '演示接口未配置' } });
    }
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.setDefaultTimeout(10000);
  return { context, page, errors, mobile, url };
}

const button = (scope, name) => scope.getByRole('button', { name, exact: true });
const dialog = page => page.locator('.el-dialog:visible, .el-drawer:visible').last();
async function settle(page) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(750);
  await page.waitForFunction(() => ![...document.querySelectorAll('.el-loading-mask')].some(x => x.getBoundingClientRect().height && getComputedStyle(x).opacity !== '0'));
  await page.mouse.move(0, 0);
}
async function go(state, route) {
  await state.page.goto(`${state.url}/#${route}`);
  await settle(state.page);
}
async function selectField(page, form, label, value) {
  await form.locator('.el-form-item').filter({ has: page.locator('.el-form-item__label', { hasText: label }) }).locator('.el-select').first().click();
  await page.getByRole('option').filter({ hasText: value }).first().click();
}
async function openJob(state, create = false) {
  await go(state, '/home');
  const { page, mobile } = state;
  if (create) {
    await button(page, '新建作业').click();
    await selectField(page, dialog(page), '引擎', 'TaoSync');
    await dialog(page).getByPlaceholder('用来标识你的作业，选填').fill('家庭相册备份');
    await button(dialog(page), '选择选择目录').first().click();
    await page.locator('.el-tree-node__label').getByText('家庭相册', { exact: true }).click();
    await button(dialog(page), '确定').click();
    await button(dialog(page), '选择选择目录').first().click();
    await page.locator('.el-tree-node__label').getByText('家庭备份', { exact: true }).click();
    await button(dialog(page), '确定').click();
    if (mobile) await dialog(page).locator('.el-drawer__body').evaluate(x => { x.scrollTop = 0; });
  } else {
    if (mobile) await button(page.locator('.job-card').nth(3), '编辑').click();
    else {
      await page.locator('.el-table__expand-icon').nth(3).click();
      await button(page.locator('.el-table__expanded-cell'), '编辑').click();
    }
  }
  await settle(page);
}
async function directories(state) {
  await go(state, '/engine');
  await button(state.page, '目录管理').click();
  await settle(state.page);
}
async function mount(state, index) {
  await directories(state);
  await button(state.page.locator('.mount-item').nth(index), '编辑').click();
  await settle(state.page);
}

export const scenes = [
  { id: 'login', zh: '登录', en: 'Sign In', run: async s => { await go(s, '/login'); await s.page.getByPlaceholder('请输入用户名').fill(user.userName); } },
  { id: 'reset-password', zh: '重置密码', en: 'Reset Password', run: async s => { await go(s, '/login'); await s.page.locator('.forgot').click(); await dialog(s.page).getByRole('textbox').first().fill(user.userName); } },
  { id: 'jobs', zh: '作业管理', en: 'Job Management', run: s => go(s, '/home') },
  { id: 'jobs-dark', zh: '深色模式', en: 'Dark Mode', run: async s => { await go(s, '/home'); await s.page.locator('.el-switch').filter({ has: s.page.getByRole('switch', { name: '切换暗色主题' }) }).click(); } },
  { id: 'job-options', zh: '作业配置概览', en: 'Job Configuration Overview', run: async s => {
    await go(s, '/home');
    if (s.mobile) {
      await s.page.locator('.job-card').nth(3).evaluate(x => x.scrollIntoView({ block: 'start' }));
      await s.page.locator('.app-main').evaluate(x => { x.scrollTop -= 64; });
    }
    else await s.page.locator('.el-table__expand-icon').nth(3).click();
  } },
  { id: 'job-create', zh: '新建作业', en: 'Create Job', run: s => openJob(s, true) },
  { id: 'job-edit', zh: '编辑作业', en: 'Edit Job', run: s => openJob(s) },
  { id: 'job-filters', zh: '扫描与过滤配置', en: 'Scanning and Filters', run: async s => { await openJob(s); await dialog(s.page).locator('.size-filter-form-item, .file-size-filter').last().scrollIntoViewIfNeeded(); } },
  { id: 'path-picker', zh: '选择同步目录', en: 'Select Sync Directory', run: async s => {
    await openJob(s); await button(dialog(s.page), '更换选择目录').first().click();
    await s.page.getByRole('treeitem').filter({ hasText: '家庭相册' }).locator('.el-tree-node__expand-icon').first().click();
    await s.page.locator('.el-tree-node__label').getByText('桃桃成长', { exact: true }).first().click();
  } },
  { id: 'job-live', zh: '实时同步进度', en: 'Live Sync Progress', run: s => go(s, '/home/task?jobId=1') },
  { id: 'job-history', zh: '任务历史', en: 'Task History', run: s => go(s, '/home/task?jobId=2') },
  { id: 'task-files', zh: '任务文件明细', en: 'Task File Details', run: s => go(s, '/home/task/detail?taskId=208') },
  { id: 'task-paths', zh: '文件路径详情', en: 'File Path Details', run: async s => {
    await go(s, '/home/task/detail?taskId=208');
    if (!s.mobile) await s.page.locator('.el-table__expand-icon').nth(1).click();
    else {
      await s.page.locator('.task-item-card').nth(1).evaluate(x => x.scrollIntoView({ block: 'start' }));
      await s.page.locator('.app-main').evaluate(x => { x.scrollTop -= 64; });
    }
  } },
  { id: 'task-filter', zh: '筛选失败文件', en: 'Filter Failed Files', run: async s => {
    await go(s, '/home/task/detail?taskId=208'); await s.page.locator('.task-detail .el-select, .mobile-filters .el-select').first().click();
    await s.page.getByRole('option', { name: '已失败', exact: true }).click();
  } },
  { id: 'engines', zh: '引擎管理', en: 'Engine Management', run: s => go(s, '/engine') },
  { id: 'engine-create', zh: '新增引擎', en: 'Add Engine', run: async s => {
    await go(s, '/engine'); await s.page.locator('.card-add').click();
    const fields = dialog(s.page).getByRole('textbox'); await fields.nth(0).fill('http://192.168.1.40:5244'); await fields.nth(1).fill('家庭影音库');
  } },
  { id: 'engine-edit', zh: '编辑引擎', en: 'Edit Engine', run: async s => { await go(s, '/engine'); await button(s.page.locator('.card-item').nth(1), '编辑').click(); } },
  { id: 'directories', zh: '目录管理', en: 'Directory Management', run: directories },
  { id: 'directory-create', zh: '新增目录', en: 'Add Directory', run: async s => {
    await directories(s); await button(dialog(s.page), '添加目录').click();
    await dialog(s.page).getByPlaceholder('用于作业路径的顶层目录名称').fill('旅行相册');
    await dialog(s.page).getByPlaceholder('请输入本机已存在的目录路径').fill('D:\\家庭资料\\旅行相册');
  } },
  { id: 'directory-local', zh: '本地目录配置', en: 'Local Directory Settings', run: s => mount(s, 0) },
  { id: 'local-browser', zh: '浏览本地目录', en: 'Browse Local Directories', run: async s => { await mount(s, 0); await s.page.getByRole('button', { name: '浏览本地目录', exact: true }).click(); } },
  { id: 'directory-smb', zh: 'SMB 目录配置', en: 'SMB Directory Settings', run: s => mount(s, 1) },
  { id: 'smb-devices', zh: '发现局域网设备', en: 'Discover Network Devices', run: async s => { await mount(s, 1); await s.page.getByRole('button', { name: '扫描 SMB 设备', exact: true }).click(); } },
  { id: 'smb-shares', zh: '发现共享目录', en: 'Discover Shared Directories', run: async s => { await mount(s, 1); await s.page.getByRole('button', { name: '扫描 SMB 共享', exact: true }).click(); } },
  { id: 'directory-ftp', zh: 'FTP 目录配置', en: 'FTP Directory Settings', run: s => mount(s, 3) },
  { id: 'directory-sftp', zh: 'SFTP 目录配置', en: 'SFTP Directory Settings', run: s => mount(s, 2) },
  { id: 'sftp-browser', zh: '浏览 SFTP 目录', en: 'Browse SFTP Directories', run: async s => {
    await mount(s, 2); await button(dialog(s.page), '测试连接').click();
    await s.page.getByText('连接已测试', { exact: true }).waitFor();
    await s.page.getByRole('button', { name: '选择目录', exact: true }).click();
    await s.page.locator('.el-tree-node__label').getByText('家庭相册', { exact: true }).click();
    await s.page.waitForTimeout(3000);
  } },
  { id: 'directory-aliyun', zh: '阿里云盘目录配置', en: 'Aliyun Drive Directory Settings', run: s => mount(s, 4) },
  { id: 'notifications', zh: '通知配置', en: 'Notification Settings', run: s => go(s, '/notify') },
  { id: 'notification-edit', zh: '编辑通知', en: 'Edit Notification', run: async s => { await go(s, '/notify'); await button(s.page.locator('.card-item').nth(1), '编辑').click(); } },
  { id: 'notification-webhook', zh: '自定义通知', en: 'Custom Notification', run: async s => { await go(s, '/notify'); await button(s.page.locator('.card-item').nth(4), '编辑').click(); } },
  { id: 'settings', zh: '系统设置', en: 'System Settings', run: s => go(s, '/setting') },
  { id: 'change-password', zh: '修改密码', en: 'Change Password', run: async s => { await go(s, '/setting'); await s.page.locator('.header-user').click(); await s.page.getByRole('menuitem', { name: '修改密码' }).click(); } },
];

export async function captureScene(state, scene) {
  await scene.run(state);
  await settle(state.page);
  assert.deepEqual(state.errors, [], `Browser errors in ${scene.id}`);
  assert.equal(await state.page.locator('.el-message--error:visible, .el-notification:visible').count(), 0);
  const overflow = await state.page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  assert.equal(overflow, false, `Horizontal document overflow in ${scene.id}`);
  await mkdir(output, { recursive: true });
  const filename = `${scene.id}-${state.mobile ? 'mobile' : 'desktop'}.png`;
  await state.page.screenshot({ path: path.join(output, filename), animations: 'disabled', fullPage: false });
  return filename;
}

async function main() {
  const require = createRequire(import.meta.url);
  const { chromium } = process.env.PLAYWRIGHT_MODULE_PATH ? require(process.env.PLAYWRIGHT_MODULE_PATH) : require('playwright');
  const server = await createDemoServer();
  const browser = await chromium.launch(process.env.SCREENSHOT_BROWSER_EXECUTABLE ? { executablePath: process.env.SCREENSHOT_BROWSER_EXECUTABLE, headless: true } : { headless: true });
  try {
    const selected = process.env.SCREENSHOT_SCENES?.split(',');
    const errors = [];
    const viewports = process.env.SCREENSHOT_VIEWPORT === 'desktop' ? [false] : process.env.SCREENSHOT_VIEWPORT === 'mobile' ? [true] : [false, true];
    for (const mobile of viewports) {
      for (const scene of scenes.filter(s => !selected || selected.includes(s.id))) {
        const state = await preparePage(browser, server.url, mobile);
        try { console.log(await captureScene(state, scene)); }
        catch (error) { errors.push(`${scene.id} (${mobile ? 'mobile' : 'desktop'}): ${error.message}`); console.error(errors.at(-1)); }
        finally { await state.context.close(); }
      }
    }
    assert.deepEqual(errors, [], 'Screenshot capture failed');
  } finally {
    await browser.close();
    await server.close();
  }
}

if (typeof process !== 'undefined' && process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch(error => { console.error(error); process.exitCode = 1; });
}
