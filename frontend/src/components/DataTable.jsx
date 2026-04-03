import React from 'react'
import { Table } from 'antd'

export default function DataTable({ columns, rows }) {
  if (!columns || !rows) return null

  const antColumns = columns.map((col) => ({
    title: col,
    dataIndex: col,
    key: col,
    ellipsis: true,
  }))

  const dataSource = rows.map((row, index) => ({
    key: index,
    ...row,
  }))

  return (
    <Table
      columns={antColumns}
      dataSource={dataSource}
      size="small"
      pagination={rows.length > 10 ? { pageSize: 10, size: 'small' } : false}
      scroll={{ x: 'max-content' }}
      style={{ marginTop: 8 }}
    />
  )
}
