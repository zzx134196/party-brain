import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { StyleProvider, legacyLogicalPropertiesTransformer } from '@ant-design/cssinjs'
import App from './App'
import './index.css'
import applyGapPolyfill from './utils/flexGapPolyfill'

// 检测并修复 flex gap 不支持的浏览器（如360信创浏览器）
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', applyGapPolyfill)
} else {
  applyGapPolyfill()
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <StyleProvider hashPriority="high" transformers={[legacyLogicalPropertiesTransformer]}>
      <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#1677ff' } }}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ConfigProvider>
    </StyleProvider>
  </React.StrictMode>
)
