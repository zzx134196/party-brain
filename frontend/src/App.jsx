import React, { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Result, Button, Spin } from 'antd'
import useAuthStore from './stores/useAuthStore'
import ChatPage from './pages/Chat'

function PrivateRoute({ children }) {
  const { isAuthenticated, token } = useAuthStore()

  // 有 token 但还没拿到 user → 加载中
  if (token && !useAuthStore.getState().user) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" tip="正在验证身份..." />
      </div>
    )
  }

  if (!isAuthenticated) {
    return (
      <Result
        status="403"
        title="请从总系统登录"
        subTitle="本系统需要通过统一认证平台登录后使用"
      />
    )
  }

  return children
}

export default function App() {
  const initAuth = useAuthStore((s) => s.initAuth)

  useEffect(() => {
    initAuth()
  }, [initAuth])

  return (
    <Routes>
      <Route
        path="/"
        element={
          <PrivateRoute>
            <ChatPage />
          </PrivateRoute>
        }
      />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

