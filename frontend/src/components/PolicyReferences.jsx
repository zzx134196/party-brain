import React, { useState } from 'react'
import { Card, Collapse, Tag, Typography, Space } from 'antd'
import { BookOutlined, FileTextOutlined } from '@ant-design/icons'

const { Text, Paragraph } = Typography

export default function PolicyReferences({ data }) {
  if (!data || data.type !== 'policy_answer' || !data.sources || data.sources.length === 0) return null

  return (
    <Card
      size="small"
      style={{ marginTop: 8, borderRadius: 8, borderLeft: '3px solid #722ed1' }}
    >
      <div style={{ marginBottom: 8 }}>
        <Space>
          <BookOutlined style={{ color: '#722ed1' }} />
          <Text strong style={{ fontSize: 13 }}>参考依据（{data.sources.length}条）</Text>
        </Space>
      </div>
      <Collapse
        size="small"
        ghost
        items={data.sources.map((src, i) => ({
          key: i,
          label: (
            <Space size={4}>
              <Tag color="purple" style={{ fontSize: 11 }}>{src.source || '未知来源'}</Tag>
              <Text style={{ fontSize: 12 }}>{src.title || src.hierarchy || `条款${i + 1}`}</Text>
              {src.score && <Tag style={{ fontSize: 10 }}>匹配度:{Math.round(src.score)}</Tag>}
            </Space>
          ),
          children: (
            <div style={{ fontSize: 12, color: '#555', lineHeight: 1.8, padding: '4px 0' }}>
              {src.hierarchy && <div style={{ color: '#999', marginBottom: 4 }}>{src.hierarchy}</div>}
              <Paragraph style={{ fontSize: 12, margin: 0 }}>{src.content}</Paragraph>
            </div>
          ),
        }))}
      />
    </Card>
  )
}
