import React from 'react'
import { Card, Tag, Progress, Typography, Descriptions, Alert, Space, Button, Divider } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, QuestionCircleOutlined, SafetyCertificateOutlined } from '@ant-design/icons'

const { Text, Paragraph } = Typography

const RESULT_ICONS = {
  PASS: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  FAIL: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
  UNKNOWN: <QuestionCircleOutlined style={{ color: '#faad14' }} />,
}

const RESULT_COLORS = { PASS: 'success', FAIL: 'error', UNKNOWN: 'warning' }

export default function ComplianceCard({ data }) {
  if (!data || data.type !== 'compliance_result') return null

  const result = data.result
  if (!result) return null

  const check = result.check_result || {}
  const preview = result.clause_preview || {}
  const confidence = Math.round((result.confidence || 0) * 100)
  const needsReview = result.needs_human_review

  const overallColor = check.overall_result === '符合' ? '#52c41a' : check.overall_result === '不符合' ? '#ff4d4f' : '#faad14'

  return (
    <Card
      size="small"
      title={<Space><SafetyCertificateOutlined style={{ color: '#1677ff' }} />合规判断结果</Space>}
      style={{ marginTop: 8, borderRadius: 8 }}
    >
      {/* 条款预览 */}
      {preview.relevant_clauses && preview.relevant_clauses.length > 0 && (
        <div style={{ marginBottom: 12, padding: '8px 12px', background: '#f6f8fa', borderRadius: 6, fontSize: 12 }}>
          <Text type="secondary">找到相关条款（{preview.relevant_clauses.length}条）：</Text>
          {preview.relevant_clauses.map((c, i) => (
            <div key={i} style={{ marginTop: 4 }}>
              <Text style={{ fontSize: 12 }}>• {c.source} {c.clause_id}: {c.summary}</Text>
            </div>
          ))}
        </div>
      )}

      {/* 判断概要 */}
      <Descriptions size="small" column={2} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="判断对象">{check.person_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="判断事项">{check.requirement || '-'}</Descriptions.Item>
        <Descriptions.Item label="综合结论">
          <Tag color={overallColor === '#52c41a' ? 'green' : overallColor === '#ff4d4f' ? 'red' : 'orange'}>
            {check.overall_result || '未知'}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="置信度">
          <Progress percent={confidence} size="small" strokeColor={confidence >= 80 ? '#52c41a' : '#faad14'} style={{ width: 120 }} />
        </Descriptions.Item>
      </Descriptions>

      {/* 逐条核查 */}
      {check.checks && check.checks.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Text strong style={{ fontSize: 13 }}>逐项核查：</Text>
          <div style={{ marginTop: 8, border: '1px solid #f0f0f0', borderRadius: 6, overflow: 'hidden' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 70px 1fr', padding: '6px 12px', background: '#fafafa', fontWeight: 500, fontSize: 12 }}>
              <span>审核条件</span><span>结果</span><span>说明</span>
            </div>
            {check.checks.map((item, i) => (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 70px 1fr', padding: '8px 12px', borderTop: '1px solid #f0f0f0', fontSize: 12 }}>
                <span>{item.condition}</span>
                <span>
                  <Tag color={RESULT_COLORS[item.result] || 'default'} style={{ fontSize: 11 }}>
                    {RESULT_ICONS[item.result]} {item.result}
                  </Tag>
                </span>
                <span style={{ color: '#666' }}>{item.explanation}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 缺失信息 */}
      {check.missing_info && check.missing_info.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message="建议补充信息"
          description={
            <ul style={{ margin: '4px 0', paddingLeft: 20, fontSize: 12 }}>
              {check.missing_info.map((info, i) => <li key={i}>{info}</li>)}
            </ul>
          }
          style={{ marginBottom: 12 }}
        />
      )}

      {/* 引用依据 */}
      {check.references && check.references.length > 0 && (
        <div style={{ padding: '8px 12px', background: '#f9f0ff', borderRadius: 6, borderLeft: '3px solid #722ed1', marginBottom: 12 }}>
          <Text strong style={{ fontSize: 12 }}>判断依据：</Text>
          {check.references.map((ref, i) => (
            <div key={i} style={{ fontSize: 12, marginTop: 4 }}>
              <Text>📎 {ref.source} {ref.clause}</Text>
              {ref.content && <Paragraph style={{ fontSize: 11, color: '#666', margin: '2px 0 0 18px' }}>{ref.content}</Paragraph>}
            </div>
          ))}
        </div>
      )}

      {/* 人工复核提示 */}
      {needsReview && (
        <Alert type="info" showIcon message={`置信度${confidence}%，建议人工复核`} style={{ marginBottom: 12 }} />
      )}

      {/* 操作按钮 */}
      <Space>
        <Button size="small">补充材料重新判断</Button>
        <Button size="small">导出判断书</Button>
      </Space>
    </Card>
  )
}
