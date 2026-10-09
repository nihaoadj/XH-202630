# 学习报告浏览器专项

`frontend/tests/reportUiBrowser.test.mjs` 使用 Playwright 和本地 Node HTTP fixture，读取已构建的 `frontend/dist`；它已登记在 `tests/suites.json` 的 browser 组。专项不访问真实后端，不修改真实业务数据，也不构建 dist。

从仓库根目录运行：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:report-ui-browser
node frontend/tests/run.mjs browser --output frontend/tests/test-results/ui-repair/frontend-browser.json
```

fixture 提供两个学习画像、长方向名与建议、掌握度节点、含未测值的资源难度序列、带状态和边的学习路径、初始诊断与空态。API 审计记录 GET 查询、`If-None-Match` 与响应码，覆盖 7/30/90 天窗口、304、强制刷新、SSE `report_changed`、离线提示和历史页导航后的样式隔离。所有请求都由本地 fixture 响应。

专项检查 1393×871 桌面、1331×871 收起侧栏、1920×1080、390×844、375×667 和 1393×620 短窗口的横向溢出、控件触达、重叠、长文案、44px 主控件、Tab 焦点、对比度及 reduced motion。空画像时刷新按钮禁用，图标保持 14px 且为 `#8ca1ae`。四个实际 ECharts 实例均从 `getOption()` 读取，并核对数据、颜色、字号、百分比量程、未测状态、slider zoom、雷达诊断状态、曲线空值与路径图 roam。报告不使用 ignored `reference.json`，也不冻结图表、stream、API 或任务起始源码 hash。

图表合同由可审查的固定期望直接验证：掌握度调色板和 38/66/92/74/0 等实际值，雷达轴和系列色、5 点标记及面积色，资源难度曲线系列色/图例/轴字体与空点；路径图核对节点状态色、连线色、`roundRect`、136×54 节点框及 12px 标签。

路径图边界检查在桌面和 375×667 手机视口执行。测试通过 Vue ECharts 暴露的 chart 实例读取 graph series 的实际图元，分别将节点 symbol path 和文字标签的变换后 bounding rect 转到 chart 坐标，要求所有节点框与完整标签均在可视边界内。断言允许布局动态调整，不依赖旧固定边距或节点坐标。

截图及每次运行的 `summary.json` 保存在 `frontend/tests/test-results/report-ui/`；统一聚合结果保存在 `frontend/tests/test-results/ui-repair/frontend-browser.json`。截图包含报告首屏、雷达与曲线、路径图、空态及响应式视口。
