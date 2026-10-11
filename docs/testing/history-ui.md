# 学习历史页面浏览器验收

`frontend/tests/historyUiBrowser.test.mjs` 是学习历史页面浏览器专项，使用 Playwright 和本地 HTTP fixture，不连接真实后端或模型，已登记到 `tests/suites.json` 的 browser 组。单项运行与聚合运行都通过同一脚本入口。

从仓库根目录先准备前端构建，再执行：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:history-ui-browser
node frontend/tests/run.mjs browser --output frontend/tests/test-results/ui-repair/frontend-browser.json
```

Windows 默认使用已安装的 Edge；其他平台默认使用 Playwright Chromium。可用 `HISTORY_BROWSER_CHANNEL` 或 `TEST_BROWSER_CHANNEL` 选择浏览器通道，设为空字符串时使用 Playwright Chromium。

脚本检查画像筛选、选择、刷新和删除取消/确认，四项当前学情与长文案，轮次状态/时间筛选对未关联事件的共同作用，生成/资源/测评/反馈/路径/后续任务六阶段，详情展开收起、分页和原资源/生成路由参数。近 7 天测试会隐藏较早的未关联事件并保留近期事件。删除画像后会验证替代画像自动选中、替代旅程加载且只发出一次 fixture DELETE。它还检查空画像/空旅程/孤立事件、键盘焦点、选择态对比度、减少动态效果、桌面独立滚动、移动与短窗口溢出、顶栏样式隔离，以及 API 写入、外网请求和页面错误。

截图和 `summary.json` 保存至 `frontend/tests/test-results/history-ui/`。DELETE 请求只会在脚本内确认后发送至本地 fixture，并记录在摘要中。
