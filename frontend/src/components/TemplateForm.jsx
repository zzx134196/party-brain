import React from 'react'
import { Card, Form, Input, InputNumber, Button, Space, Tag, Typography } from 'antd'
import { FileTextOutlined, SendOutlined } from '@ant-design/icons'

const { Text } = Typography

export default function TemplateForm({ data, onSubmit }) {
  const [form] = Form.useForm()

  if (!data || data.type !== 'template_form') return null

  const { template_name, provided_fields, missing_required_fields, missing_optional_fields } = data

  const handleFinish = (values) => {
    const allFields = { ...provided_fields, ...values, _template_id: data.template_id }
    onSubmit(allFields, data.template_id)
  }

  return (
    <Card
      size="small"
      title={<Space><FileTextOutlined style={{ color: '#1677ff' }} />已匹配模板：{template_name}</Space>}
      style={{ marginTop: 8, borderColor: '#1677ff', borderRadius: 8 }}
    >
      {Object.keys(provided_fields || {}).length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>已识别的信息：</Text>
          <div style={{ marginTop: 4 }}>
            {Object.entries(provided_fields).map(([k, v]) => (
              <Tag key={k} color="green">{k}: {v}</Tag>
            ))}
          </div>
        </div>
      )}

      <Form form={form} layout="vertical" onFinish={handleFinish} size="small">
        {(missing_required_fields || []).map((field) => (
          <Form.Item
            key={field}
            name={field}
            label={<span>{field} <Tag color="red" style={{ fontSize: 10 }}>必填</Tag></span>}
            rules={[{ required: true, message: `请填写${field}` }]}
          >
            <Input placeholder={`请输入${field}`} />
          </Form.Item>
        ))}

        {(missing_optional_fields || []).map((field) => (
          <Form.Item key={field} name={field} label={<span>{field} <Tag style={{ fontSize: 10 }}>选填</Tag></span>}>
            <Input placeholder={`请输入${field}（可选）`} />
          </Form.Item>
        ))}

        <Form.Item style={{ marginBottom: 0 }}>
          <Space>
            <Button type="primary" htmlType="submit" icon={<SendOutlined />}>确认生成</Button>
            <Button>取消</Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  )
}
