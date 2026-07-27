import React from 'react'
import { RouterProvider } from 'react-router-dom'
import { PublicClientApplication } from '@azure/msal-browser'
import { MsalProvider } from '@azure/msal-react'
import { msalConfig } from './custom/authConfig.js'
import { router } from './custom/router.jsx'

const msalInstance = new PublicClientApplication(msalConfig);

// 进行 MSAL v3 初始化
const initPromise = msalInstance.initialize();

function App() {
  const [initialized, setInitialized] = React.useState(false);

  React.useEffect(() => {
    initPromise.then(() => {
      setInitialized(true);
    }).catch((err) => {
      console.error("MSAL initialization failed", err);
      // 回退触发，尝试正常加载
      setInitialized(true);
    });
  }, []);

  if (!initialized) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        fontFamily: 'sans-serif',
        background: '#f4f6f9'
      }}>
        <div style={{
          border: '4px solid #f3f3f3',
          borderTop: '4px solid #3d5afe',
          borderRadius: '50%',
          width: '36px',
          height: '46px',
          boxSizing: 'border-box',
          animation: 'spin 1s linear infinite'
        }} />
        <p style={{ marginTop: '16px', color: '#666', fontSize: '14px' }}>正在加载系统环境...</p>
        <style>{`
          @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    );
  }

  return (
    <MsalProvider instance={msalInstance}>
      <RouterProvider router={router} />
    </MsalProvider>
  )
}

export default App
