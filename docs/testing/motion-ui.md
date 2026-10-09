# 页面与模块动效专项

`frontend/tests/motionBrowser.test.mjs` 使用生产构建和本地 HTTP fixture 验收页面导航及主要学习模块动效。fixture 隔离认证、画像、资源、历史、反馈和报告请求；所有业务写请求、未登记 API、外网请求、页面异常及未处理 Promise rejection 都会使专项失败。它不连接真实 API 或模型。

专项通过真实侧栏和顶栏链接遍历工作台、新建方向、资源生成、学习资源、学习反馈、学习历史、学习报告和用户资料，检查浏览器 View Transition 快照、固定应用外壳、导航完成后的 DOM 清理，并覆盖不支持原生 API 和原生启动抛错时的透明度回退、快速导航、浏览器前进/后退与运行中切换减少动态效果。同一 shell 内页面导航可使用原生快照；focus/public/auth 等 wholeLayout 外壳切换使用实时 `#app` 透明度动画，退场 80ms、进场 260ms，不启动原生快照。focus 进出均采样 `#app` 真实进场中间帧，核对 opacity、`transform: none` 和时长；退出时还在退场动画中采样固定退出按钮的真实命中目标，截图时不等待动画结束。

局部模块检查覆盖新建方向步骤中 wrapper 仅淡入、带内边距的标题按前进/返回方向位移 8px、答案和焦点保持，以及可访问的问卷卡片区域内部滚动且 app 内容区和 document 保持原位。资源材料的 query 更新复用 reader；专注模式按现有 App 分支重挂载 reader，并保留材料选择参数、library 请求次数和固定退出按钮可命中性。专项还覆盖历史画像加载后的局部淡入、报告时间窗口切换后的淡入以及 SSE 更新不重播。专项用 WAAPI `getTiming().duration` 的真实毫秒值核对模块 200ms、wholeLayout 退场 80ms/进场 260ms，同时验证共享 easing、关键帧、中间帧透明度/变换及截图，不按数值大小把秒单位推断换算成毫秒。

登录与注册路由复用 `LandingView`；两种表单互切只让 `.access-form-panel` 做 200ms 淡入，不启动整页或原生 View Transition。fixture 以未登录状态导航，不提交登录/注册请求，并在淡入中验证提交按钮仍可命中。

从仓库根目录执行：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:motion-browser
```

本地证据写入 `frontend/tests/test-results/motion-ui/`，包括 `summary.json` 和中间帧截图；该目录是忽略的验收产物。聚合浏览器入口会把本专项纳入十三项检查，须先构建前端。
