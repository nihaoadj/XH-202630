// Empty channel selects Playwright Chromium; Windows defaults to installed Edge.
export function browserOptions(channelVariable) {
  const value = Object.hasOwn(process.env, channelVariable) ? process.env[channelVariable]
    : Object.hasOwn(process.env, 'TEST_BROWSER_CHANNEL') ? process.env.TEST_BROWSER_CHANNEL
      : process.platform === 'win32' ? 'msedge' : ''
  return { headless: true, ...(value ? { channel: value } : {}) }
}
