import React from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Button } from 'primereact/button'
import { Tooltip } from 'primereact/tooltip'
import { Divider } from 'primereact/divider'
import { OverlayPanel } from 'primereact/overlaypanel'
import { useMsal } from '@azure/msal-react'
import { trackToolNavigation } from './analytics'
import { toolItems } from './tools'

const parseDepartment = (displayName) => {
  if (!displayName) return ''
  const match = displayName.match(/\(([^)]+)\)/)
  return match ? match[1] : ''
}

function Navbar() {
  const navigate = useNavigate()
  const location = useLocation()
  const [expanded, setExpanded] = React.useState(false)
  const { instance, accounts } = useMsal()
  const op = React.useRef(null)

  const homeItem = toolItems[0]
  const quickTools = toolItems.slice(1)

  // 1. 将用户信息声明为 React State 状态，保证响应式更新渲染
  const [user, setUser] = React.useState({
    name: 'Guest User',
    username: 'guest@example.com',
    department: 'Unknown Dept',
    initial: 'G'
  })

  React.useEffect(() => {
    if (accounts && accounts.length > 0) {
      const account = accounts[0]
      const name = account.name || account.username || ''
      const department = parseDepartment(name)
      let initialChar = 'U'
      if (name) {
        const cleanName = name.replace(/[^a-zA-Z\u4e00-\u9fa5]/g, '').trim()
        if (cleanName) {
          initialChar = cleanName.charAt(0).toUpperCase()
        }
      }
      setUser({
        name,
        username: account.username,
        department: department || 'No Department',
        initial: initialChar
      })
    } else {
      // 如果 accounts 没到位，自动读取 sessionStorage 缓存
      try {
        const cachedInfo = window.sessionStorage.getItem('user_info')
        if (cachedInfo) {
          const parsed = JSON.parse(cachedInfo)
          let initialChar = 'U'
          if (parsed.name) {
            const cleanName = parsed.name.replace(/[^a-zA-Z\u4e00-\u9fa5]/g, '').trim()
            if (cleanName) {
              initialChar = cleanName.charAt(0).toUpperCase()
            }
          }
          setUser({
            name: parsed.name || 'User',
            username: parsed.username || '',
            department: parsed.department || 'No Department',
            initial: initialChar
          })
        }
      } catch (e) {
        console.error('Error fetching cached user info', e)
      }
    }
  }, [accounts])

  const handleLogout = () => {
    window.sessionStorage.removeItem('user_info')
    instance.logoutRedirect().catch((e) => {
      console.error('Logout failed', e)
    })
  }

  const handleNavigate = (tool, source) => {
    trackToolNavigation(tool, source)
    navigate(tool.path)
  }

  return (
    <aside className={`app-sidebar ${expanded ? 'is-expanded' : 'is-collapsed'}`}>
      <Tooltip target='.sidebar-action' position='right' disabled={expanded} />

      <Button
        className='sidebar-action sidebar-toggle'
        rounded
        text
        severity='secondary'
        icon={expanded ? 'pi pi-angle-left' : 'pi pi-bars'}
        data-pr-tooltip={expanded ? '收起侧边栏' : '展开侧边栏'}
        onClick={() => setExpanded((prev) => !prev)}
      />

      {expanded && (
        <>
          <Divider className='sidebar-divider' />

          <div className='sidebar-tools'>
            {quickTools.map((item) => {
              const isActive = location.pathname.startsWith(item.path)
              return (
                <Button
                  key={item.key}
                  className='sidebar-action'
                  rounded
                  text
                  severity={isActive ? 'primary' : 'secondary'}
                  icon={item.icon}
                  onClick={() => handleNavigate(item, 'sidebar_quick')}
                >
                  <span className='sidebar-label'>{item.title}</span>
                </Button>
              )
            })}
          </div>
        </>
      )}

      {!expanded && (
        <div className='sidebar-tools'>
          {quickTools.map((item) => {
            const isActive = location.pathname.startsWith(item.path)
            return (
              <Button
                key={item.key}
                className='sidebar-action'
                rounded
                text
                severity={isActive ? 'primary' : 'secondary'}
                icon={item.icon}
                data-pr-tooltip={item.title}
                onClick={() => handleNavigate(item, 'sidebar_quick')}
              />
            )
          })}
        </div>
      )}

      <div className='sidebar-home-slot'>
        <Button
          className='sidebar-action'
          rounded
          text
          severity={location.pathname === homeItem.path ? 'primary' : 'secondary'}
          icon={homeItem.icon}
          data-pr-tooltip='返回首页'
          onClick={() => handleNavigate(homeItem, 'sidebar_home')}
        >
          {expanded && <span className='sidebar-label'>{homeItem.title}</span>}
        </Button>

        {/* 精美用户头像与名片触发器 */}
        <div className='avatar-container' style={{ background: expanded ? '#f8fafc' : 'transparent', padding: expanded ? '10px' : '0', border: expanded ? '1px solid #f1f5f9' : 'none' }}>
          <div 
            className='user-avatar-circle' 
            onClick={(e) => op.current.toggle(e)}
          >
            {user.initial}
          </div>
          {expanded && (
            <div className='avatar-info-box' onClick={(e) => op.current.toggle(e)} style={{ cursor: 'pointer' }}>
              <span className='avatar-name'>{user.name.split(' (')[0]}</span>
              <span className='avatar-dept'>{user.department}</span>
            </div>
          )}
        </div>

        {/* 弹出式微软风格个人卡片 */}
        <OverlayPanel ref={op} style={{ width: '280px', borderRadius: '12px', boxShadow: '0 8px 30px rgba(0,0,0,0.15)', background: '#ffffff', border: '1px solid #e2e8f0' }}>
          <div style={{ padding: '4px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                background: 'linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%)',
                color: '#ffffff',
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                fontWeight: '600',
                fontSize: '18px'
              }}>
                {user.initial}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <span style={{ fontWeight: '600', fontSize: '15px', color: '#1e293b', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {user.name.split(' (')[0]}
                </span>
                <span style={{ fontSize: '12px', color: '#64748b', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {user.username}
                </span>
              </div>
            </div>

            <Divider style={{ margin: '8px 0' }} />

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', margin: '12px 0 16px 0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12.5px' }}>
                <span style={{ color: '#64748b' }}>用户部门：</span>
                <span style={{ fontWeight: '500', color: '#334155', textAlign: 'right' }}>{user.department}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12.5px' }}>
                <span style={{ color: '#64748b' }}>认证账号：</span>
                <span style={{ fontWeight: '500', color: '#334155' }}>Microsoft Active</span>
              </div>
            </div>

            <Button
              label='退出账户'
              icon='pi pi-sign-out'
              severity='danger'
              outlined
              onClick={handleLogout}
              style={{ width: '100%', borderRadius: '8px', padding: '8px', fontSize: '13px' }}
            />
          </div>
        </OverlayPanel>
      </div>
    </aside>
  )
}

export default Navbar