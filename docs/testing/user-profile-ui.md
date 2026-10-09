# 用户资料页浏览器专项

`frontend/tests/userProfileUiBrowser.test.mjs` 使用本地 Node HTTP fixture 和 Playwright 打开已构建的 `frontend/dist`，核对 `/user/profile` 的表单、保存行为、窄屏布局、键盘可达性和页面样式隔离。脚本已登记到 `tests/suites.json` 的 browser 组；不执行构建、不调用真实后端或外部网络。

从仓库根目录运行：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:user-profile-ui-browser
node frontend/tests/run.mjs browser --output frontend/tests/test-results/ui-repair/frontend-browser.json
```

运行前需由主流程构建 `frontend/dist`，并安装前端依赖。浏览器通道遵循 `frontend/tests/browserOptions.mjs`：可用 `USER_PROFILE_UI_BROWSER_CHANNEL` 指定；未设置时沿用 `TEST_BROWSER_CHANNEL` 或平台默认值。

Fixture 提供 auth/current user、学习方向查询、空历史页及唯一允许写入的 `PATCH /api/users/fixture-user-42`。成功响应直接返回 user；失败 fixture 返回 503，用于核对失败后表单内容和已保存概览是否保留、loading 是否恢复以及能否重试。专项检查用户名只读，以及身份、学历、专业、岗位/背景、经验年限字段的 id、aria-label、maxlength 和数值范围；还验证精确 PATCH payload、空值 fallback、`experience_years=0/null` 与 auth/localStorage 持久化。失败时页面预期的提示和 `console.error` 单独记录，不与未捕获页面错误混为一项。

布局视口为 1393×871、1331×871（侧栏收起）、1920×1080、1393×620、390×844 和 375×667。专项检查横向溢出、面板和顶栏重叠、输入框与主要按钮高度、保存操作可达性、长文案换行、键盘 Tab 焦点、减少动态效果和指定文字颜色对比度。还会核对新建方向入口，以及经用户资料页进入学习历史时的主题样式与直接访问一致。

页面字段、保存、失败/重试与路由行为构成验收合同，不依赖页面或共享文件的任务起始 SHA256。运行摘要、fixture 请求记录及截图保存在 `frontend/tests/test-results/user-profile-ui/`；`summary.json` 记录逐项 PASS/FAIL、各 viewport 几何测量、首屏保存按钮可见性与写入审计。
