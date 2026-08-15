import React from 'react'
import { Card, Tag, Typography, Space, Descriptions, Divider, Progress } from 'antd'
import { DiffOutlined, PlusCircleOutlined, MinusCircleOutlined, EditOutlined } from '@ant-design/icons'

const { Text, Paragraph } = Typography

const TYPE_CONFIG = {
  '修改': { color: 'orange', icon: <EditOutlined /> },
  '新增': { color: 'green', icon: <PlusCircleOutlined /> },
  '删除': { color: 'red', icon: <MinusCircleOutlined /> },
}

export default function DiffReport({ data }) {
  if (!data || data.type !== 'diff_report') return null

  const report = data.report || {}
  const diffs = report.diffs || []
  const summary = report.summary || {}
  const similarity = report.similarity || 0

  return (
    <Card
      size="small"
      title={<Space><DiffOutlined style={{ color: '#1890ff' }} />文件差异报告</Space>}
      style={{ marginTop: 8, borderRadius: 8 }}
    >
      {/* 文件信息 */}
      <Descriptions size="small" column={2} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="文件1">{report.file1 || '-'}</Descriptions.Item>
        <Descriptions.Item label="文件2">{report.file2 || '-'}</Descriptions.Item>
        <Descriptions.Item label="差异数量">
          <Text strong style={{ color: diffs.length > 0 ? '#ff4d4f' : '#52c41a' }}>{report.total_diffs || diffs.length} 处</Text>
        </Descriptions.Item>
        <Descriptions.Item label="相似度">
          <Progress percent={similarity} size="small" style={{ width: 100 }} strokeColor={similarity > 80 ? '#52c41a' : '#faad14'} />
        </Descriptions.Item>
      </Descriptions>

      {/* AI 分析降级提示 */}
      {report.fallback && (
        <div style={{ marginBottom: 12, padding: '8px 12px', background: '#fffbe6', border: '1px solid #ffe58f', borderRadius: 6, fontSize: 12, color: '#ad6800', lineHeight: 1.7 }}>
          {report.message || '⚠️ AI语义差异分析暂不可用，已使用基础文本差异规则输出清单，建议人工复核。'}
        </div>
      )}

      {/* 差异汇总 */}
      {(summary.modified > 0 || summary.added > 0 || summary.deleted > 0) && (
        <div className="flex-gap-8" style={{ marginBottom: 12, display: 'flex' }}>
          {summary.modified > 0 && <Tag color="orange">修改 {summary.modified} 处</Tag>}
          {summary.added > 0 && <Tag color="green">新增 {summary.added} 处</Tag>}
          {summary.deleted > 0 && <Tag color="red">删除 {summary.deleted} 处</Tag>}
        </div>
      )}

      {/* 差异详情 */}
      {diffs.length > 0 && (
        <div>
          {diffs.map((diff, i) => {
            const config = TYPE_CONFIG[diff.type] || TYPE_CONFIG['修改']
            return (
              <div key={i} style={{ marginBottom: 12, padding: '8px 12px', background: '#fafafa', borderRadius: 6, borderLeft: `3px solid ${config.color === 'orange' ? '#fa8c16' : config.color === 'green' ? '#52c41a' : '#ff4d4f'}` }}>
                <div style={{ marginBottom: 6 }}>
                  <Space>
                    <Tag color={config.color} icon={config.icon}>{diff.type}</Tag>
                    <Text strong style={{ fontSize: 12 }}>{diff.location || `差异 #${diff.index || i + 1}`}</Text>
                    {diff.severity && <Tag style={{ fontSize: 10 }}>{diff.severity}</Tag>}
                  </Space>
                </div>

                {diff.old_text && (
                  <div style={{ fontSize: 12, marginBottom: 4 }}>
                    <Text type="secondary">旧版：</Text>
                    <span style={{ background: '#fff1f0', padding: '1px 4px', borderRadius: 2 }}>{diff.old_text.slice(0, 200)}{diff.old_text.length > 200 ? '...' : ''}</span>
                  </div>
                )}
                {diff.new_text && (
                  <div style={{ fontSize: 12, marginBottom: 4 }}>
                    <Text type="secondary">新版：</Text>
                    <span style={{ background: '#f6ffed', padding: '1px 4px', borderRadius: 2 }}>{diff.new_text.slice(0, 200)}{diff.new_text.length > 200 ? '...' : ''}</span>
                  </div>
                )}
                {diff.summary && (
                  <div style={{ fontSize: 11, color: '#666', marginTop: 4 }}>
                    变更说明：{diff.summary}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {diffs.length === 0 && report.message && (
        <Text type="secondary">{report.message}</Text>
      )}
    </Card>
  )
}
