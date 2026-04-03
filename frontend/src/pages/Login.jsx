import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Form, Input, Button, message, Typography } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import useAuthStore from '../stores/useAuthStore'
import { authApi } from '../services/api'

const { Title, Text } = Typography

export default function LoginPage() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)

  const onFinish = async (values) => {
    setLoading(true)
    try {
      const res = await authApi.login(values.username, values.password)
      login(res.access_token, res.user)
      message.success('登录成功')
      navigate('/')
    } catch (err) {
      message.error(err.response?.data?.detail || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)',
      }}
    >
      <Card
        style={{ width: 400, borderRadius: 14, boxShadow: '0 12px 40px rgba(0,0,0,0.25)', border: 'none' }}
        bodyStyle={{ padding: '36px 32px 28px' }}
      >
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{
            width: 52, height: 52, borderRadius: 14, margin: '0 auto 14px',
            background: 'linear-gradient(135deg, #1677ff, #4096ff)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 4px 16px rgba(22,119,255,0.3)',
          }}>
            <span style={{ color: '#fff', fontSize: 24, fontWeight: 700 }}>智</span>
          </div>
          <Title level={3} style={{ marginBottom: 4, color: '#1a1a1a' }}>
            智慧党建助手
          </Title>
          <Text type="secondary" style={{ fontSize: 13 }}>机关党委智能工作平台</Text>
        </div>

        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined style={{ color: '#bbb' }} />} placeholder="用户名" style={{ borderRadius: 8 }} />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined style={{ color: '#bbb' }} />} placeholder="密码" style={{ borderRadius: 8 }} />
          </Form.Item>
          <Form.Item style={{ marginBottom: 16 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              style={{
                height: 44, borderRadius: 8, fontWeight: 500,
                background: 'linear-gradient(135deg, #1677ff, #4096ff)',
                border: 'none', boxShadow: '0 2px 8px rgba(22,119,255,0.3)',
              }}
            >
              登 录
            </Button>
          </Form.Item>
        </Form>

        <div style={{ textAlign: 'center' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            请联系管理员获取账号
          </Text>
        </div>
      </Card>
    </div>
  )
}
