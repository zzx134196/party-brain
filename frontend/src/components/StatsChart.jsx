import React from 'react'
import ReactECharts from 'echarts-for-react'
import { Card, Tabs } from 'antd'

export default function StatsChart({ data }) {
  if (!data || !data.is_stats || !data.rows || data.rows.length === 0) return null

  const columns = data.columns || []
  const rows = data.rows || []

  // 尝试识别分类列和数值列
  let categoryCol = columns[0]
  let valueCol = columns.find((c) => {
    const sample = rows[0]?.[c]
    return typeof sample === 'number' || (!isNaN(Number(sample)) && c !== categoryCol)
  }) || columns[1]

  const categories = rows.map((r) => String(r[categoryCol] || ''))
  const values = rows.map((r) => Number(r[valueCol]) || 0)

  const barOption = {
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: categories, axisLabel: { interval: 0, rotate: categories.length > 6 ? 30 : 0 } },
    yAxis: { type: 'value' },
    series: [{ data: values, type: 'bar', itemStyle: { color: '#1677ff', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 40 }],
    grid: { left: 40, right: 20, bottom: 40, top: 20 },
  }

  const pieOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['35%', '65%'],
      data: categories.map((name, i) => ({ name, value: values[i] })),
      label: { formatter: '{b}\n{d}%', fontSize: 12 },
      itemStyle: { borderRadius: 4 },
    }],
  }

  return (
    <Card size="small" style={{ marginTop: 8, borderRadius: 8 }}>
      <Tabs
        size="small"
        items={[
          { key: 'bar', label: '柱状图', children: <ReactECharts option={barOption} style={{ height: 260 }} /> },
          { key: 'pie', label: '饼状图', children: <ReactECharts option={pieOption} style={{ height: 260 }} /> },
        ]}
      />
    </Card>
  )
}
