import React from 'react'
import { Card, Descriptions, Tag, Avatar, Space, Typography } from 'antd'
import { UserOutlined, PhoneOutlined, TeamOutlined, IdcardOutlined } from '@ant-design/icons'

const { Text } = Typography

const STATUS_COLORS = { '正式': 'green', '预备': 'orange', '转出': 'default' }

export default function ProfileCard({ data }) {
  if (!data || data.type !== 'member_profile') return null

  const m = data.member || {}

  return (
    <Card
      size="small"
      style={{ marginTop: 8, borderRadius: 8, borderLeft: '3px solid #1890ff' }}
    >
      <div className="flex-gap-12" style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
        <Avatar size={48} icon={<UserOutlined />} style={{ background: '#1890ff' }} />
        <div>
          <Space>
            <Text strong style={{ fontSize: 16 }}>{m.name}</Text>
            <Tag color={STATUS_COLORS[m.status] || 'default'}>{m.status || '未知'}</Tag>
            <Tag icon={<TeamOutlined />}>{m.department || '未知支部'}</Tag>
          </Space>
          <div><Text type="secondary" style={{ fontSize: 12 }}>{m.position || ''}</Text></div>
        </div>
      </div>
      <Descriptions size="small" column={2} bordered>
        <Descriptions.Item label="性别">{m.gender || '-'}</Descriptions.Item>
        <Descriptions.Item label="出生日期">{m.birth_date || '-'}</Descriptions.Item>
        <Descriptions.Item label="学历">{m.education || '-'}</Descriptions.Item>
        <Descriptions.Item label="民族">{m.ethnicity || '-'}</Descriptions.Item>
        <Descriptions.Item label="入党日期">{m.join_party_date || '-'}</Descriptions.Item>
        <Descriptions.Item label="转正日期">{m.become_full_date || '-'}</Descriptions.Item>
        <Descriptions.Item label="联系电话" span={2}>
          <Space><PhoneOutlined />{m.phone || '-'}</Space>
        </Descriptions.Item>
      </Descriptions>
    </Card>
  )
}
