const DEFAULT_EVENT_NAME = 'tool_open'
const DEFAULT_MEASUREMENT_ID = 'G-82CFXS1X70'

function hasGtag() {
  return typeof window !== 'undefined' && typeof window.gtag === 'function'
}

function getPageContext(overrides = {}) {
  if (typeof window === 'undefined') {
    return {
      page_location: undefined,
      page_path: undefined,
      page_title: undefined
    }
  }

  // 获取登录用户信息并传入 GA，方便基于部门分组统计（删除个人敏感姓名上传以保障合规与隐私）
  let userDepartment = ''
  try {
    const userInfoStr = window.sessionStorage.getItem('user_info')
    if (userInfoStr) {
      const userInfo = JSON.parse(userInfoStr)
      userDepartment = userInfo.department || ''
    }
  } catch (err) {
    console.error('Failed to parse user_info for analytics context', err)
  }

  return {
    page_location: window.location.href,
    page_path: `${window.location.pathname}${window.location.hash}`,
    page_title: document.title,
    user_department: userDepartment,
    ...overrides
  }
}

export function trackPageView(tool, pageOverrides = {}) {
  if (!hasGtag()) {
    return
  }

  const pageContext = getPageContext(pageOverrides)

  window.gtag('event', 'page_view', {
    send_to: DEFAULT_MEASUREMENT_ID,
    ...pageContext,
    tool_key: tool?.key,
    tool_path: tool?.path,
    tool_title: tool?.title
  })
}

export function trackToolNavigation(tool, source = 'unknown') {
  if (!tool || tool.analytics === false || !hasGtag()) {
    return
  }

  const analyticsConfig = tool.analytics || {}
  const { eventName = DEFAULT_EVENT_NAME, eventParams = {} } = analyticsConfig
  const pageContext = getPageContext()

  window.gtag('event', eventName, {
    send_to: DEFAULT_MEASUREMENT_ID,
    source,
    tool_key: tool.key,
    tool_path: tool.path,
    tool_title: tool.title,
    ...pageContext,
    ...eventParams
  })
}