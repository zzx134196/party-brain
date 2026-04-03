import React, { useState } from 'react'
import { Card, Tag, Space, Typography, Collapse, Spin } from 'antd'
import {
  BookOutlined, FileTextOutlined, SafetyCertificateOutlined,
  DownloadOutlined, SearchOutlined,
  CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined,
} from '@ant-design/icons'

const { Text } = Typography

const TOOL_CONFIG = {
  search_policy: { label: '正在检索政策法规...', done: '已找到相关政策', icon: <BookOutlined />, color: '#722ed1' },
  check_compliance: { label: '正在进行合规分析...', done: '合规分析完成', icon: <SafetyCertificateOutlined />, color: '#fa8c16' },
  list_templates: { label: '正在获取模板信息...', done: '已获取模板信息', icon: <FileTextOutlined />, color: '#52c41a' },
  generate_document: { label: '正在生成文档...', done: '文档生成完成', icon: <FileTextOutlined />, color: '#1677ff' },
  export_file: { label: '正在准备文件...', done: '文件已准备就绪', icon: <DownloadOutlined />, color: '#52c41a' },
  compare_texts: { label: '正在分析文本差异...', done: '差异分析完成', icon: <SearchOutlined />, color: '#eb2f96' },
}

export function ToolCallingCard({ tool, args }) {
  const config = TOOL_CONFIG[tool] || { label: '正在处理...', icon: <SearchOutlined />, color: '#999' }

  return (
    <div style={{
      margin: '6px 0',
      padding: '6px 12px',
      background: '#f6f8fa',
      borderRadius: 8,
      borderLeft: `3px solid ${config.color}`,
      fontSize: 12,
    }}>
      <Space>
        <Spin indicator={<LoadingOutlined style={{ fontSize: 14, color: config.color }} />} />
        <span style={{ color: config.color }}>{config.icon}</span>
        <Text style={{ fontSize: 12, color: '#666' }}>{config.label}</Text>
      </Space>
    </div>
  )
}

export function ToolResultCard({ tool, success, summary, structured }) {
  const config = TOOL_CONFIG[tool] || { label: '处理完成', done: '处理完成', icon: <SearchOutlined />, color: '#999' }

  return (
    <div style={{
      margin: '6px 0',
      padding: '6px 12px',
      background: success ? '#f6ffed' : '#fff2f0',
      borderRadius: 8,
      borderLeft: `3px solid ${success ? '#52c41a' : '#ff4d4f'}`,
      fontSize: 12,
    }}>
      <Space>
        {success
          ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
          : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
        }
        <span style={{ color: config.color }}>{config.icon}</span>
        <Text style={{ fontSize: 12, color: success ? '#52c41a' : '#ff4d4f' }}>{summary || config.done || '完成'}</Text>
      </Space>
    </div>
  )
}

export default function ToolCallTimeline({ toolCalls }) {
  if (!toolCalls || toolCalls.length === 0) return null

  return (
    <div style={{ margin: '8px 0' }}>
      {toolCalls.map((tc, i) => {
        const config = TOOL_CONFIG[tc.tool] || { done: '完成', icon: <SearchOutlined />, color: '#999' }
        const ok = tc.success !== undefined ? tc.success : true
        return (
          <div key={i} style={{
            margin: '3px 0',
            padding: '4px 10px',
            background: ok ? '#f6ffed' : '#fff2f0',
            borderRadius: 6,
            borderLeft: `3px solid ${ok ? '#52c41a' : '#ff4d4f'}`,
            fontSize: 11,
          }}>
            <Space size={4}>
              {ok ? <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 11 }} /> : <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 11 }} />}
              <span style={{ color: config.color, fontSize: 11 }}>{config.icon}</span>
              <Text style={{ fontSize: 11, color: ok ? '#52c41a' : '#ff4d4f' }}>{tc.summary || config.done || '完成'}</Text>
            </Space>
          </div>
        )
      })}
    </div>
  )
}
