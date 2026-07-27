import React from 'react'
import {
  createHashRouter,
  createRoutesFromElements,
  Route,
  Outlet,
  useLocation,
  useNavigate
} from 'react-router-dom'
import { useMsal, useIsAuthenticated } from '@azure/msal-react'
import { Button } from 'primereact/button'
import HomePage from './HomePage'
import Navbar from './Navbar'
import ToolFrame from './ToolFrame'
import { trackPageView } from './analytics'
import { loginRequest } from './authConfig'
import { portalTools, toolItems } from './tools'

function PageTracker() {
  const location = useLocation()

  React.useEffect(() => {
    const matchedTool = toolItems.find((item) => {
      if (item.path === '/') {
        return location.pathname === '/'
      }

      return location.pathname.startsWith(item.path)
    })
    const pageTitle = matchedTool ? `OnePager Tools - ${matchedTool.title}` : 'OnePager Tools'

    if (typeof document !== 'undefined') {
      document.title = pageTitle
    }

    trackPageView(matchedTool, {
      page_title: pageTitle,
      page_path: `${window.location.pathname}${window.location.hash}`,
      page_location: window.location.href
    })
  }, [location])

  return null
}

const parseDepartment = (displayName) => {
  if (!displayName) return ''
  // 匹配圆括号中的内容，如 "QIAN Aiur (VM-OSS/EPH2-CN)" -> "VM-OSS/EPH2-CN"
  const match = displayName.match(/\(([^)]+)\)/)
  return match ? match[1] : ''
}

const RootLayout = () => {
  const { instance, accounts, inProgress } = useMsal()
  const isAuthenticated = useIsAuthenticated()
  const navigate = useNavigate()

  // 1. 登录成功后，解析账户信息、用户部门并存入 sessionStorage
  React.useEffect(() => {
    if (isAuthenticated && accounts.length > 0) {
      const account = accounts[0]
      const name = account.name || account.username || ''
      const department = parseDepartment(name)
      const userInfo = {
        name,
        username: account.username,
        department,
        homeAccountId: account.homeAccountId
      }
      window.sessionStorage.setItem('user_info', JSON.stringify(userInfo))

      // 2. 检查是否有需要恢复的子域名哈希路由
      const postLoginRedirect = window.sessionStorage.getItem('post_login_redirect')
      if (postLoginRedirect) {
        window.sessionStorage.removeItem('post_login_redirect')
        let targetPath = postLoginRedirect.replace(/^#/, '')
        if (!targetPath.startsWith('/')) {
          targetPath = '/' + targetPath
        }
        // 如果 targetPath 不为空且不是首页，则进行跳转
        if (targetPath && targetPath !== '/') {
          navigate(targetPath, { replace: true })
        }
      }
    }
  }, [isAuthenticated, accounts, navigate])

  const handleLogin = () => {
    // 登录前，备份当前的路由哈希（排除首页 '/'）
    const hash = window.location.hash
    if (hash && hash !== '#/') {
      window.sessionStorage.setItem('post_login_redirect', hash)
    }
    instance.loginRedirect(loginRequest).catch((error) => {
      console.error('SSO Login fail', error)
    })
  }

  // 3. 正在加载/握手状态
  if (inProgress !== 'none') {
    return (
      <div className="login-wrapper" style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        background: '#f4f6f9',
        fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
      }}>
        <div style={{
          border: '4px solid #f3f3f3',
          borderTop: '4px solid #3d5afe',
          borderRadius: '50%',
          width: '36px',
          height: '36px',
          animation: 'spin 1s linear infinite'
        }} />
        <p style={{ marginTop: '16px', color: '#666', fontSize: '14px' }}>正在同 Microsoft Entra ID 进行验证...</p>
        <style>{`
          @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    )
  }

  // 4. 未登录拦截，渲染精美的登录面板
  if (!isAuthenticated) {
    return (
      <div className="login-wrapper" style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        background: 'linear-gradient(135deg, #1e3c72 0%, #2a5298 100%)',
        fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
      }}>
        <div className="login-card" style={{
          background: 'rgba(255, 255, 255, 0.95)',
          padding: '40px',
          borderRadius: '16px',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.24)',
          width: '400px',
          textAlign: 'center',
          backdropFilter: 'blur(8px)',
          border: '1px solid rgba(255, 255, 255, 0.2)'
        }}>
          {/* Legend Microsoft Squares */}
          <div style={{ display: 'flex', justifyContent: 'center', gap: '4px', marginBottom: '24px' }}>
            <div style={{ width: '16px', height: '16px', background: '#f25022' }} />
            <div style={{ width: '16px', height: '16px', background: '#7fba00' }} />
            <div style={{ width: '16px', height: '16px', background: '#00a4ef' }} />
            <div style={{ width: '16px', height: '16px', background: '#ffb900' }} />
          </div>
          <h2 style={{ fontSize: '24px', margin: '0 0 10px 0', color: '#1a1a1a', fontWeight: '600' }}>Broom OnePager</h2>
          <p style={{ fontSize: '14px', color: '#666', margin: '0 0 30px 0' }}>请使用您的微软域账号登录以访问应用</p>
          
          <Button
            label="使用 Microsoft 账号登录"
            icon="pi pi-microsoft"
            onClick={handleLogin}
            style={{
              width: '100%',
              padding: '12px',
              borderRadius: '8px',
              fontSize: '15px',
              fontWeight: '500',
              background: '#0078d4',
              borderColor: '#0078d4',
              color: '#ffffff'
            }}
          />

          <div style={{ marginTop: '24px', fontSize: '12px', color: '#999' }}>
            内部发布应用平台 | Azure SSO 强身份验证
          </div>
        </div>
      </div>
    )
  }

  // 5. 登录成功
  return (
    <div className='app-shell'>
      <PageTracker />
      <Navbar />
      <main className='app-main'>
        <Outlet />
      </main>
    </div>
  )
}

export const router = createHashRouter(
  createRoutesFromElements(
    <Route path='' element={<RootLayout />}>
      <Route index element={<HomePage />} />
      {portalTools.map((tool) => {
        const routeSegment = tool.path.replace(/^\//, '')
        return (
          <Route
            key={tool.key}
            path={`${routeSegment}/*`}
            element={<ToolFrame tool={tool} toolPath={tool.toolPath || routeSegment} title={tool.title} />}
          />
        )
      })}
    </Route>
  ),
)