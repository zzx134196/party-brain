import React, { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Layout, Input, Button, Typography, Space, Avatar, Spin, Dropdown, Tag, Upload, Modal, message as antMessage,
} from 'antd'
import {
  SendOutlined, PlusOutlined, UserOutlined, RobotOutlined, FileTextOutlined,
  BookOutlined, AuditOutlined, DiffOutlined, DownloadOutlined, EditOutlined,
  SettingOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined, CloseOutlined,
  QuestionCircleOutlined, CheckCircleOutlined, ReloadOutlined, UploadOutlined,
  PaperClipOutlined, DeleteOutlined, LoadingOutlined, UpOutlined, DownOutlined,
} from '@ant-design/icons'
import useAuthStore from '../stores/useAuthStore'
import useChatStore from '../stores/useChatStore'
import { chatApi, diffApi } from '../services/api'
import TemplateForm from '../components/TemplateForm'
import ComplianceCard from '../components/ComplianceCard'
import PolicyReferences from '../components/PolicyReferences'
import DiffReport from '../components/DiffReport'
import ToolCallTimeline, { ToolCallingCard, ToolResultCard } from '../components/ToolCallCard'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const { Header, Sider, Content } = Layout
const { Text, Title, Paragraph } = Typography
const { TextArea } = Input


export default function ChatPage() {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()
  const {
    messages, currentConversationId, loading, streaming,
    addMessage, updateLastMessage, appendThinkingContent, setLoading, setStreaming,
    setCurrentConversation, setMessages, clearChat,
  } = useChatStore()

  const [inputValue, setInputValue] = useState('')
  const [siderCollapsed, setSiderCollapsed] = useState(false)
  const [conversations, setConversations] = useState([])
  const [useStream] = useState(true)

  // 附件状态
  const [attachment, setAttachment] = useState(null)  // { filename, text, charCount }
  const [attachUploading, setAttachUploading] = useState(false)
  const fileInputRef = useRef(null)
  const [diffModalOpen, setDiffModalOpen] = useState(false)
  const [diffFile1, setDiffFile1] = useState(null)
  const [diffFile2, setDiffFile2] = useState(null)
  const [diffLoading, setDiffLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const messagesEndRef = useRef(null)
  const messagesContainerRef = useRef(null)
  const inputRef = useRef(null)
  const abortRef = useRef(null)  // 用于取消流式请求

  // 加载对话历史列表
  useEffect(() => {
    chatApi.getConversations().then(setConversations).catch(() => {})
  }, [currentConversationId])

  // 消息更新时滚动到底部
  useEffect(() => {
    const el = messagesContainerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  // 流式输出期间持续滚动到底部
  useEffect(() => {
    if (!streaming) return
    let raf
    const tick = () => {
      const el = messagesContainerRef.current
      if (el) el.scrollTop = el.scrollHeight
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [streaming])

  // 切换到历史对话
  const handleSwitchConversation = async (convId) => {
    try {
      setCurrentConversation(convId)
      const msgs = await chatApi.getMessages(convId)
      setMessages(msgs)
    } catch (err) {
      // ignore
    }
  }

  // 流式SSE回调处理（复用于 handleSend 和 handleActionStream）
  const _handleStreamChunk = (data) => {
    if (data.type === 'thinking') {
      const currentMsgs = useChatStore.getState().messages
      if (currentMsgs.length > 0) {
        const last = currentMsgs[currentMsgs.length - 1]
        if (last.role === 'assistant' && !last.content) {
          useChatStore.getState().updateLastMessageMeta({ thinking: data.message })
        }
      }
    } else if (data.type === 'thinking_content') {
      useChatStore.getState().appendThinkingContent(data.text)
    } else if (data.type === 'tool_calling') {
      useChatStore.getState().updateLastMessageMeta({ thinking: null })
      useChatStore.getState().appendToolEvent({ type: 'calling', tool: data.tool, args: data.args })
    } else if (data.type === 'tool_result') {
      useChatStore.getState().appendToolEvent({ type: 'result', tool: data.tool, success: data.success, summary: data.summary, structured: data.structured })
    } else if (data.content) {
      updateLastMessage(data.content)
    }
    if (data.done) {
      if (data.conversation_id) setCurrentConversation(data.conversation_id)
      if (data.data || data.actions || data.tool_calls) {
        useChatStore.getState().updateLastMessageMeta({
          data: data.data, actions: data.actions, tool_calls: data.tool_calls, intent: 'agent',
        })
      }
    }
  }

  // 按钮操作专用的流式发送（不显示用户消息，AI直接接着输出）
  const handleActionStream = async (msg, context = null) => {
    if (loading || streaming) return
    try {
      setStreaming(true)
      addMessage({ role: 'assistant', content: '', toolEvents: [], created_at: new Date().toISOString() })
      const payload = { conversation_id: currentConversationId, message: msg }
      if (context) payload.context = context
      await chatApi.sendMessageStream(payload, _handleStreamChunk)
    } catch (err) {
      updateLastMessage('\n\n[操作中断，请重试]')
    } finally {
      setStreaming(false)
    }
  }

  // 附件上传处理
  const handleAttachFile = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    const ALLOWED = ['.pdf', '.docx', '.doc', '.txt', '.wps', '.md']
    const ext = '.' + file.name.split('.').pop().toLowerCase()
    if (!ALLOWED.includes(ext)) {
      antMessage.error(`不支持的格式 ${ext}，仅支持 ${ALLOWED.join('/')}`)
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      antMessage.error('文件大小不能超过 10MB')
      return
    }
    try {
      setAttachUploading(true)
      const res = await chatApi.uploadAttachment(file)
      setAttachment({ filename: res.filename, text: res.text, charCount: res.char_count })
      antMessage.success(`已附加「${res.filename}」(${res.char_count}字)`)
    } catch (err) {
      antMessage.error(err.response?.data?.detail || '文件上传失败')
    } finally {
      setAttachUploading(false)
    }
  }

  const handleSend = async (text) => {
    const msg = (text || inputValue).trim()
    if (!msg || loading || streaming) return
    const curAttachment = attachment
    setInputValue('')
    setAttachment(null)

    // 用户消息中显示附件提示
    const displayMsg = curAttachment ? `${msg}\n📎 附件: ${curAttachment.filename}` : msg
    addMessage({ role: 'user', content: displayMsg, created_at: new Date().toISOString() })

    if (useStream) {
      // Agent流式输出模式 — 支持工具调用过程展示
      try {
        setStreaming(true)
        addMessage({ role: 'assistant', content: '', toolEvents: [], created_at: new Date().toISOString() })

        const payload = { conversation_id: currentConversationId, message: msg }
        if (curAttachment) {
          payload.attachment_text = curAttachment.text
          payload.attachment_name = curAttachment.filename
        }
        abortRef.current = new AbortController()
        await chatApi.sendMessageStream(payload, _handleStreamChunk, abortRef.current.signal)
      } catch (err) {
        if (err?.name !== 'AbortError') {
          updateLastMessage('\n\n[流式输出中断，请重试]')
        }
      } finally {
        abortRef.current = null
        setStreaming(false)
      }
    } else {
      // 非流式模式（支持结构化数据返回）
      try {
        setLoading(true)
        const res = await chatApi.sendMessage({
          conversation_id: currentConversationId,
          message: msg,
        })

        if (!currentConversationId) {
          setCurrentConversation(res.conversation_id)
        }

        addMessage({
          role: 'assistant',
          content: res.reply,
          intent: res.intent,
          data: res.data,
          actions: res.actions,
          tool_calls: res.tool_calls,
          created_at: new Date().toISOString(),
        })
      } catch (err) {
        addMessage({
          role: 'assistant',
          content: '抱歉，处理您的请求时遇到了问题，请稍后重试。',
          created_at: new Date().toISOString(),
        })
      } finally {
        setLoading(false)
      }
    }
  }

  // 暴露给TemplateForm和动作按钮的回调
  useEffect(() => {
    window.__chatSendWithContext = async (params) => {
      // 自动注入conversation_id
      const payload = { conversation_id: currentConversationId, ...params }
      try {
        setLoading(true)
        addMessage({ role: 'user', content: params.message, created_at: new Date().toISOString() })
        const res = await chatApi.sendMessage(payload)
        if (res.conversation_id) setCurrentConversation(res.conversation_id)
        addMessage({
          role: 'assistant',
          content: res.reply,
          intent: res.intent,
          data: res.data,
          actions: res.actions,
          tool_calls: res.tool_calls,
          created_at: new Date().toISOString(),
        })
      } catch (err) {
        addMessage({ role: 'assistant', content: '生成失败，请重试。', created_at: new Date().toISOString() })
      } finally {
        setLoading(false)
      }
    }
    return () => { delete window.__chatSendWithContext }
  }, [currentConversationId])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // 文件差异对比
  const handleDiffCompare = async () => {
    if (!diffFile1 || !diffFile2) {
      antMessage.warning('请上传两个文件')
      return
    }
    setDiffLoading(true)
    try {
      clearChat()
      addMessage({ role: 'user', content: `请对比文件差异：\n文件1：${diffFile1.name}\n文件2：${diffFile2.name}`, created_at: new Date().toISOString() })
      const result = await diffApi.compareFiles(diffFile1, diffFile2)
      addMessage({
        role: 'assistant',
        content: result.conclusion || '文件差异分析完成，请查看下方报告。',
        data: { type: 'diff_report', report: result },
        created_at: new Date().toISOString(),
      })
      setDiffModalOpen(false)
    } catch (err) {
      antMessage.error('文件对比失败：' + (err.response?.data?.detail || err.message))
    } finally {
      setDiffLoading(false)
    }
  }

  // 处理动作按钮点击（下载Word/PDF/Excel等）
  const handleAction = async (action, message) => {
    const token = localStorage.getItem('token')
    const headers = { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' }

    // 非下载类动作（确认大纲、修改等）直接分发，不走下载流程
    if (action.type === 'confirm_outline' && message.data) {
      handleActionStream('确认大纲，请生成完整文档', {
        ...(message.data.fields || {}),
        _confirm_outline: true,
        _template_id: message.data.template_id,
      })
      return
    } else if (action.type === 'regenerate_outline' && message.data) {
      handleActionStream('请重新生成大纲', {
        ...(message.data.fields || {}),
        _template_id: message.data.template_id,
      })
      return
    } else if (action.type === 'modify' && message.data?.content) {
      const modification = window.prompt('请输入修改要求（如：把预算部分再详细些）')
      if (modification && modification.trim()) {
        handleActionStream(modification.trim(), {
          _modify_document: true,
          _original_content: message.data.content,
          _template_name: message.data.template_name,
        })
      }
      return
    } else if (action.type === 'supplement_info') {
      const supplement = window.prompt('请输入补充信息（如：已完成党支部推荐，群众评议通过）')
      if (supplement && supplement.trim()) {
        handleActionStream(supplement.trim() + '，请重新进行合规判断')
      }
      return
    }

    // ===== 以下为文件下载类动作 =====
    setExporting(true)
    try {
      let response, filename
      const docTitle = message.data?.template_name || '文档'

      if (action.type === 'download_word' && message.data?.content) {
        antMessage.loading({ content: '正在生成 Word 文件...', key: 'export', duration: 0 })
        response = await fetch('/api/export/word', {
          method: 'POST', headers,
          body: JSON.stringify({ title: docTitle, content: message.data.content }),
        })
        filename = `${docTitle}.docx`

      } else if (action.type === 'download_pdf' && message.data?.content) {
        antMessage.loading({ content: '正在生成 PDF 文件...', key: 'export', duration: 0 })
        response = await fetch('/api/export/pdf', {
          method: 'POST', headers,
          body: JSON.stringify({ title: docTitle, content: message.data.content }),
        })
        filename = `${docTitle}.pdf`

      } else if (action.type === 'export_report' && message.data?.result) {
        // 导出合规判断书 — 将结构化结果转为文本后导出 Word
        antMessage.loading({ content: '正在生成判断书...', key: 'export', duration: 0 })
        const r = message.data.result
        const lines = [
          `判断对象：${r.person_name || '—'}`,
          `判断事项：${r.requirement || '—'}`,
          `综合结论：${r.overall_result || '—'}`,
          `置信度：${r.confidence != null ? (r.confidence * 100).toFixed(0) + '%' : '—'}`,
          '',
          '一、逐条审核',
          ...(r.checks || []).map((c, i) =>
            `${i + 1}. ${c.condition}　结果：${c.result}　说明：${c.explanation || '—'}`
          ),
        ]
        if (r.missing_info?.length) {
          lines.push('', '二、缺失信息', ...r.missing_info.map((m, i) => `${i + 1}. ${m}`))
        }
        if (r.suggestions?.length) {
          lines.push('', '三、建议', ...r.suggestions.map((s, i) => `${i + 1}. ${s}`))
        }
        if (r.references?.length) {
          lines.push('', '四、引用依据', ...r.references.map((ref, i) =>
            `${i + 1}. ${ref.source} ${ref.clause || ''}: ${ref.content || ''}`
          ))
        }
        response = await fetch('/api/export/word', {
          method: 'POST', headers,
          body: JSON.stringify({ title: '合规判断书', content: lines.join('\n') }),
        })
        filename = `合规判断书_${r.person_name || '未知'}.docx`

      } else {
        setExporting(false)
        return
      }

      // 检查响应状态
      if (!response.ok) {
        let errMsg = `导出失败 (${response.status})`
        try {
          const errData = await response.json()
          errMsg = errData.detail || errMsg
        } catch (_) {}
        antMessage.error({ content: errMsg, key: 'export', duration: 3 })
        setExporting(false)
        return
      }

      const blob = await response.blob()
      if (blob && blob.size > 0) {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        antMessage.success({ content: `${filename} 下载成功`, key: 'export', duration: 2 })
      } else {
        antMessage.error({ content: '导出的文件为空，请重试', key: 'export', duration: 3 })
      }
    } catch (err) {
      console.error('导出失败:', err)
      antMessage.error({ content: '导出失败: ' + (err.message || '网络异常'), key: 'export', duration: 3 })
    } finally {
      setExporting(false)
    }
  }

  const handleDeleteConversation = async (convId) => {
    try {
      await chatApi.deleteConversation(convId)
      setConversations((prev) => prev.filter((c) => c.id !== convId))
      if (convId === currentConversationId) {
        clearChat()
      }
    } catch (err) {
      // ignore
    }
  }

  const handleNewChat = () => {
    clearChat()
    inputRef.current?.focus()
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const userMenu = {
    items: [
      { key: 'logout', label: '退出登录', icon: <LogoutOutlined />, onClick: handleLogout },
    ],
  }

  return (
    <Layout style={{ height: '100vh' }}>
      {/* 左侧栏 */}
      <Sider
        width={260}
        collapsedWidth={0}
        collapsed={siderCollapsed}
        style={{ background: 'linear-gradient(180deg, #fff 0%, #fafbfc 100%)', borderRight: '1px solid #eee', overflow: 'auto' }}
      >
        <div style={{ padding: '14px 16px', borderBottom: '1px solid #f0f0f0' }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            block
            onClick={handleNewChat}
            style={{ borderRadius: 8, height: 40, fontWeight: 500, background: 'linear-gradient(135deg, #1677ff 0%, #4096ff 100%)', border: 'none', boxShadow: '0 2px 8px rgba(22,119,255,0.3)' }}
          >
            新对话
          </Button>
        </div>

        {/* 对话历史 */}
        {conversations.length > 0 && (
          <>
            <div style={{ padding: '14px 16px 6px', borderTop: '1px solid #f0f0f0', marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, textTransform: 'uppercase' }}>历史对话</Text>
            </div>
            <div style={{ padding: '0 8px', maxHeight: 180, overflow: 'auto' }}>
              {conversations.slice(0, 15).map((conv) => (
                <div
                  key={conv.id}
                  style={{
                    display: 'flex', alignItems: 'center', marginBottom: 2,
                    borderRadius: 4,
                    background: conv.id === currentConversationId ? '#e6f4ff' : undefined,
                  }}
                >
                  <Button
                    type="text"
                    size="small"
                    style={{
                      flex: 1, textAlign: 'left', height: 32, fontSize: 12,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}
                    onClick={() => handleSwitchConversation(conv.id)}
                  >
                    {conv.title}
                  </Button>
                  <CloseOutlined
                    style={{ fontSize: 10, color: '#999', padding: '0 6px', cursor: 'pointer', flexShrink: 0 }}
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDeleteConversation(conv.id)
                    }}
                  />
                </div>
              ))}
            </div>
          </>
        )}

        {/* 工具 */}
        <div style={{ padding: '14px 16px 6px', borderTop: '1px solid #f0f0f0', marginTop: 4 }}>
          <Text type="secondary" style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, textTransform: 'uppercase' }}>工具</Text>
        </div>
        <div style={{ padding: '0 8px' }}>
          <Button type="text" icon={<DiffOutlined />} block style={{ textAlign: 'left', height: 36 }}
            onClick={() => { setDiffFile1(null); setDiffFile2(null); setDiffModalOpen(true) }}>
            文件差异对比
          </Button>
        </div>


      </Sider>

      {/* 主内容区 */}
      <Layout>
        <Header
          style={{
            background: '#fff', padding: '0 20px', display: 'flex',
            alignItems: 'center', justifyContent: 'space-between',
            borderBottom: '1px solid #f0f0f0', height: 52,
            boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
          }}
        >
          <Space align="center">
            <Button
              type="text"
              icon={siderCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setSiderCollapsed(!siderCollapsed)}
              style={{ fontSize: 16 }}
            />
            <div className="flex-gap-8" style={{ display: 'flex', alignItems: 'center' }}>
              <div style={{ width: 28, height: 28, borderRadius: 6, background: 'linear-gradient(135deg, #1677ff, #4096ff)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span style={{ color: '#fff', fontSize: 14, fontWeight: 700 }}>智</span>
              </div>
              <Title level={4} style={{ margin: 0, color: '#1a1a1a', fontSize: 16, fontWeight: 600 }}>智慧党建助手</Title>
            </div>
          </Space>
          <Dropdown menu={userMenu} placement="bottomRight">
            <Space style={{ cursor: 'pointer', padding: '4px 8px', borderRadius: 8, transition: 'background 0.2s' }}>
              <Avatar size={28} icon={<UserOutlined />} style={{ background: 'linear-gradient(135deg, #1677ff, #4096ff)' }} />
              <Text style={{ fontSize: 13 }}>{user?.real_name || user?.username}</Text>
              {user?.role === 'admin' && <Tag color="blue" style={{ margin: 0, fontSize: 11, lineHeight: '18px', height: 20 }}>管理员</Tag>}
            </Space>
          </Dropdown>
        </Header>

        <Content style={{ display: 'flex', flexDirection: 'column', background: '#f5f6f8' }}>
          {/* 消息列表 */}
          <div ref={messagesContainerRef} style={{ flex: 1, overflow: 'auto', padding: '20px 24px 0' }}>
            {messages.length === 0 ? (
              <WelcomeScreen onSend={handleSend} />
            ) : (
              messages.map((msg, index) => (
                <MessageBubble key={index} message={msg} onAction={handleAction} exporting={exporting} />
              ))
            )}
            {loading && (
              <div style={{ textAlign: 'center', padding: 16 }}>
                <Spin tip="思考中..." />
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* 输入区 */}
          <div style={{ padding: '10px 24px 14px', background: '#fff', borderTop: '1px solid #eee', boxShadow: '0 -2px 8px rgba(0,0,0,0.03)' }}>
            <div style={{ maxWidth: 800, margin: '0 auto' }}>
              {/* 已附加文件提示 */}
              {attachment && (
                <div className="flex-gap-8" style={{
                  display: 'flex', alignItems: 'center',
                  padding: '6px 12px', marginBottom: 6,
                  background: '#f0f5ff', borderRadius: 8, border: '1px solid #d6e4ff',
                }}>
                  <PaperClipOutlined style={{ color: '#1677ff' }} />
                  <Text style={{ fontSize: 13, flex: 1 }}>
                    {attachment.filename}
                    <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>({attachment.charCount}字)</Text>
                  </Text>
                  <CloseOutlined
                    style={{ cursor: 'pointer', color: '#999', fontSize: 12 }}
                    onClick={() => setAttachment(null)}
                  />
                </div>
              )}
              <div className="flex-gap-8" style={{
                display: 'flex', alignItems: 'flex-end',
                background: '#f7f8fa', borderRadius: 12, padding: '8px 8px 8px 10px',
                border: '1px solid #e8e8e8', transition: 'border-color 0.3s, box-shadow 0.3s',
              }}>
                {/* 附件上传按钮 */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx,.doc,.txt,.wps,.md"
                  style={{ display: 'none' }}
                  onChange={handleAttachFile}
                />
                <Button
                  type="text"
                  icon={attachUploading ? <LoadingOutlined /> : <PaperClipOutlined />}
                  onClick={() => fileInputRef.current?.click()}
                  disabled={loading || streaming || attachUploading}
                  title="上传参考文件"
                  style={{ height: 36, width: 36, borderRadius: 8, flexShrink: 0, color: '#666' }}
                />
                <TextArea
                  ref={inputRef}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="请输入您的问题...（Enter发送，Shift+Enter换行）"
                  autoSize={{ minRows: 1, maxRows: 4 }}
                  style={{ borderRadius: 6, border: 'none', background: 'transparent', resize: 'none', boxShadow: 'none', padding: '4px 0', fontSize: 14 }}
                  disabled={loading || streaming}
                />
                {streaming ? (
                  <Button
                    danger
                    icon={<span style={{ fontSize: 14 }}>■</span>}
                    onClick={() => { if (abortRef.current) abortRef.current.abort() }}
                    style={{
                      height: 36, minWidth: 36, borderRadius: 8, flexShrink: 0, padding: '0 14px',
                      fontWeight: 500,
                    }}
                  >
                    停止
                  </Button>
                ) : (
                  <Button
                    type="primary"
                    icon={<SendOutlined />}
                    onClick={() => handleSend()}
                    loading={loading}
                    disabled={!inputValue.trim()}
                    style={{
                      height: 36, minWidth: 36, borderRadius: 8, flexShrink: 0, padding: '0 14px',
                      background: inputValue.trim() ? 'linear-gradient(135deg, #1677ff, #4096ff)' : undefined,
                      border: 'none', boxShadow: inputValue.trim() ? '0 2px 6px rgba(22,119,255,0.3)' : 'none',
                    }}
                  >
                    发送
                  </Button>
                )}
              </div>
              <div style={{ marginTop: 6, padding: '0 4px' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  Enter 发送，Shift+Enter 换行 | 📎 可附加参考文件
                </Text>
              </div>
            </div>
          </div>
        </Content>
      </Layout>

      {/* 文件差异对比弹窗 */}
      <Modal
        title={<Space><DiffOutlined style={{ color: '#722ed1' }} />文件差异对比</Space>}
        open={diffModalOpen}
        onCancel={() => { if (!diffLoading) setDiffModalOpen(false) }}
        onOk={handleDiffCompare}
        okText="开始对比"
        cancelText="取消"
        confirmLoading={diffLoading}
        okButtonProps={{ disabled: !diffFile1 || !diffFile2 }}
        destroyOnClose
      >
        <div className="flex-col-gap-16" style={{ display: 'flex', flexDirection: 'column', padding: '12px 0' }}>
          <div>
            <Text strong style={{ fontSize: 13, marginBottom: 8, display: 'block' }}>文件1</Text>
            <Upload
              beforeUpload={(file) => { setDiffFile1(file); return false }}
              onRemove={() => setDiffFile1(null)}
              fileList={diffFile1 ? [diffFile1] : []}
              accept=".pdf,.docx,.doc,.txt"
              maxCount={1}
            >
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
          </div>
          <div>
            <Text strong style={{ fontSize: 13, marginBottom: 8, display: 'block' }}>文件2</Text>
            <Upload
              beforeUpload={(file) => { setDiffFile2(file); return false }}
              onRemove={() => setDiffFile2(null)}
              fileList={diffFile2 ? [diffFile2] : []}
              accept=".pdf,.docx,.doc,.txt"
              maxCount={1}
            >
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
          </div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            支持 PDF、Word（.docx/.doc）、TXT 格式
          </Text>
        </div>
      </Modal>
    </Layout>
  )
}

/* 欢迎页面 */
function WelcomeScreen({ onSend }) {
  const features = [
    {
      icon: <FileTextOutlined />, color: '#1677ff', bg: '#e6f4ff',
      title: '文档模板生成', desc: '工作计划、活动方案、会议纪要等',
      examples: [
        '帮我写一份主题党日活动方案',
        '生成一份季度工作总结',
      ],
    },
    {
      icon: <BookOutlined />, color: '#52c41a', bg: '#f6ffed',
      title: '政策法规咨询', desc: '政策查询、条款解读',
      examples: [
        '公务接待有什么规定？',
        '省直机关差旅费标准是什么？',
      ],
    },
    {
      icon: <AuditOutlined />, color: '#fa8c16', bg: '#fff7e6',
      title: '合规条件判断', desc: '逐条对照、置信度评估',
      examples: [
        '某单位拟举办50人会议，预算8万元是否合规？',
      ],
    },
  ]

  return (
    <div style={{ maxWidth: 720, margin: '40px auto', textAlign: 'center' }}>
      {/* Logo + 标题 */}
      <div style={{ marginBottom: 20 }}>
        <div style={{
          width: 56, height: 56, borderRadius: 14, margin: '0 auto 16px',
          background: 'linear-gradient(135deg, #1677ff 0%, #4096ff 100%)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 4px 16px rgba(22,119,255,0.25)',
        }}>
          <span style={{ color: '#fff', fontSize: 26, fontWeight: 700 }}>智</span>
        </div>
        <Title level={3} style={{ color: '#1a1a1a', marginBottom: 4, fontWeight: 600 }}>
          智慧党建助手
        </Title>
        <Paragraph type="secondary" style={{ fontSize: 14, marginBottom: 0 }}>
          智能生成文档 · 解答政策问题 · 合规条件判断
        </Paragraph>
      </div>

      {/* 功能卡片 + 示例 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, textAlign: 'left' }}>
        {features.map((item, i) => (
          <div
            key={i}
            style={{
              padding: '16px 18px', borderRadius: 12,
              background: '#fff', border: '1px solid #f0f0f0',
              transition: 'all 0.25s ease',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = item.color; e.currentTarget.style.boxShadow = `0 2px 12px ${item.color}18` }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#f0f0f0'; e.currentTarget.style.boxShadow = 'none' }}
          >
            {/* 功能头部 */}
            <div className="flex-gap-10" style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
              <div style={{
                width: 36, height: 36, borderRadius: 9, background: item.bg,
                display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                fontSize: 17, color: item.color,
              }}>
                {item.icon}
              </div>
              <div>
                <Text strong style={{ fontSize: 13 }}>{item.title}</Text>
                <br />
                <Text type="secondary" style={{ fontSize: 11 }}>{item.desc}</Text>
              </div>
            </div>
            {/* 可点击的示例 */}
            <div className="flex-col-gap-6" style={{ display: 'flex', flexDirection: 'column' }}>
              {item.examples.map((q, j) => (
                <div
                  key={j}
                  onClick={() => onSend(q)}
                  style={{
                    padding: '8px 12px', borderRadius: 8, cursor: 'pointer',
                    background: item.bg, border: `1px solid transparent`,
                    fontSize: 12, color: '#333', lineHeight: 1.5,
                    transition: 'all 0.2s ease', whiteSpace: 'pre-wrap',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = item.color; e.currentTarget.style.background = '#fff' }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'transparent'; e.currentTarget.style.background = item.bg }}
                >
                  <span style={{ color: item.color, marginRight: 6, fontWeight: 600 }}>›</span>
                  {q}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* 消息气泡 */
function MessageBubble({ message, onAction, exporting }) {
  const isUser = message.role === 'user'
  const [thinkingExpanded, setThinkingExpanded] = React.useState(true)
  const isStreaming = !message.content && !!(message.thinking || message.thinkingContent)

  return (
    <div
      className="message-enter"
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 16,
        maxWidth: 800,
        margin: '0 auto 16px',
      }}
    >
      {!isUser && (
        <Avatar
          icon={<RobotOutlined />}
          size={34}
          style={{ background: 'linear-gradient(135deg, #1677ff, #4096ff)', marginRight: 10, flexShrink: 0, boxShadow: '0 2px 6px rgba(22,119,255,0.2)' }}
        />
      )}
      <div
        style={{
          maxWidth: '78%',
          padding: '12px 16px',
          borderRadius: isUser ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
          background: isUser ? 'linear-gradient(135deg, #1677ff 0%, #4096ff 100%)' : '#fff',
          color: isUser ? '#fff' : '#333',
          boxShadow: isUser ? '0 2px 8px rgba(22,119,255,0.2)' : '0 1px 6px rgba(0,0,0,0.06)',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          lineHeight: 1.7,
          fontSize: 14,
        }}
      >
        {/* Agent思考状态提示（无内容时） */}
        {!isUser && message.thinking && !message.content && !message.thinkingContent && (
          <div className="flex-gap-8" style={{ marginBottom: 8, display: 'flex', alignItems: 'center', color: '#999', fontSize: 12 }}>
            <Spin size="small" />
            <span>{message.thinking}</span>
          </div>
        )}

        {/* 思考过程展示（可展开/收起） */}
        {!isUser && message.thinkingContent && (
          <div style={{ marginBottom: 10 }}>
            <div
              onClick={() => { if (!isStreaming) setThinkingExpanded(!thinkingExpanded) }}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '6px 12px', 
                borderRadius: (isStreaming || thinkingExpanded) ? '8px 8px 0 0' : '8px',
                background: '#f0f4ff', border: '1px solid #e0e8ff',
                borderBottom: (isStreaming || thinkingExpanded) ? 'none' : '1px solid #e0e8ff',
                color: '#5b7cfa', fontSize: 12, fontWeight: 500,
                cursor: isStreaming ? 'default' : 'pointer',
                userSelect: 'none',
                transition: 'all 0.2s',
              }}
            >
              <div className="flex-gap-6" style={{ display: 'flex', alignItems: 'center' }}>
                {isStreaming
                  ? <><Spin size="small" /><span style={{ marginLeft: 4 }}>深度思考中...</span></>
                  : <><span style={{ fontSize: 13 }}>💭</span><span>思考过程</span></>
                }
              </div>
              {!isStreaming && (
                <div style={{ fontSize: 10, color: '#88a4fa' }}>
                  {thinkingExpanded ? <UpOutlined /> : <DownOutlined />}
                </div>
              )}
            </div>
            
            {(isStreaming || thinkingExpanded) && (
              <div style={{
                padding: '10px 12px',
                background: '#f9fafe', border: '1px solid #e0e8ff',
                borderRadius: '0 0 8px 8px', fontSize: 12, color: '#666',
                lineHeight: 1.8, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                maxHeight: isStreaming ? 'none' : 400, overflow: isStreaming ? 'visible' : 'auto',
              }}>
                {message.thinkingContent}
              </div>
            )}
          </div>
        )}

        {/* Agent工具调用过程展示（流式模式） */}
        {!isUser && message.toolEvents && message.toolEvents.length > 0 && (
          <div style={{ marginBottom: 8 }}>
            {(() => {
              const events = message.toolEvents
              const resultTools = new Set(events.filter(e => e.type === 'result').map(e => e.tool))
              return events.map((evt, i) => {
                if (evt.type === 'calling' && resultTools.has(evt.tool)) {
                  return <ToolResultCard key={i} tool={evt.tool} success={true} summary="已完成" />
                }
                return evt.type === 'calling'
                  ? <ToolCallingCard key={i} tool={evt.tool} args={evt.args} />
                  : <ToolResultCard key={i} tool={evt.tool} success={evt.success} summary={evt.summary} structured={evt.structured} />
              })
            })()}
          </div>
        )}

        {/* Agent工具调用记录（标准模式） */}
        {!isUser && message.tool_calls && message.tool_calls.length > 0 && !(message.toolEvents && message.toolEvents.length > 0) && (
          <div style={{ marginBottom: 8 }}>
            <ToolCallTimeline toolCalls={message.tool_calls} />
          </div>
        )}

        {isUser ? message.content : (
          <div style={{ whiteSpace: 'normal' }}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({children}) => <h3 style={{margin: '12px 0 6px', fontSize: 16, fontWeight: 600}}>{children}</h3>,
                h2: ({children}) => <h4 style={{margin: '10px 0 4px', fontSize: 15, fontWeight: 600}}>{children}</h4>,
                h3: ({children}) => <h5 style={{margin: '8px 0 4px', fontSize: 14, fontWeight: 600}}>{children}</h5>,
                p: ({children}) => <p style={{margin: '4px 0', lineHeight: 1.7}}>{children}</p>,
                ul: ({children}) => <ul style={{margin: '4px 0', paddingLeft: 20}}>{children}</ul>,
                ol: ({children}) => <ol style={{margin: '4px 0', paddingLeft: 20}}>{children}</ol>,
                li: ({children}) => <li style={{margin: '2px 0'}}>{children}</li>,
                strong: ({children}) => <strong style={{fontWeight: 600}}>{children}</strong>,
                table: ({children}) => <table style={{borderCollapse: 'collapse', margin: '8px 0', fontSize: 12, width: '100%'}}>{children}</table>,
                th: ({children}) => <th style={{border: '1px solid #e8e8e8', padding: '6px 10px', background: '#fafafa', fontWeight: 600, textAlign: 'left'}}>{children}</th>,
                td: ({children}) => <td style={{border: '1px solid #e8e8e8', padding: '6px 10px'}}>{children}</td>,
                blockquote: ({children}) => <blockquote style={{borderLeft: '3px solid #1677ff', margin: '8px 0', paddingLeft: 12, color: '#666'}}>{children}</blockquote>,
                code: ({inline, children}) => inline
                  ? <code style={{background: '#f5f5f5', padding: '1px 4px', borderRadius: 3, fontSize: '0.9em'}}>{children}</code>
                  : <pre style={{background: '#f5f5f5', padding: 8, borderRadius: 4, overflow: 'auto', fontSize: 12}}><code>{children}</code></pre>,
                a: ({href, children}) => {
                  const isDownload = href && href.startsWith('/api/export/download/')
                  return <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      color: isDownload ? '#fff' : '#1677ff',
                      background: isDownload ? 'linear-gradient(135deg, #1677ff, #4096ff)' : 'none',
                      padding: isDownload ? '4px 12px' : 0,
                      borderRadius: isDownload ? 16 : 0,
                      display: isDownload ? 'inline-block' : 'inline',
                      textDecoration: isDownload ? 'none' : 'underline',
                      fontSize: isDownload ? 13 : 'inherit',
                      margin: isDownload ? '2px 4px' : 0,
                      boxShadow: isDownload ? '0 2px 6px rgba(22,119,255,0.2)' : 'none',
                    }}
                  >{children}</a>
                },
              }}
            >
              {message.content || ''}
            </ReactMarkdown>
          </div>
        )}

        {/* 追问表单（功能一） */}
        {message.data?.type === 'template_form' && (
          <TemplateForm data={message.data} onSubmit={(fields, templateId) => {
            window.__chatSendWithContext?.({
              message: '请根据以上信息生成文档',
              context: fields,
              conversation_id: message.conversation_id,
            })
          }} />
        )}

        {/* 政策咨询引用块（功能三） */}
        {message.data?.type === 'policy_answer' && message.data?.sources && (
          <PolicyReferences data={message.data} />
        )}

        {/* 知识库检索来源文件列表（policy_search 类型） */}
        {message.data?.type === 'policy_search' && message.data?.sources?.length > 0 && (
          <div style={{ marginTop: 10, padding: '8px 10px', background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 8 }}>
            <div className="flex-gap-4" style={{ fontSize: 11, color: '#52c41a', fontWeight: 600, marginBottom: 6, display: 'flex', alignItems: 'center' }}>
              <span>📄</span><span>参考文档（{message.data.sources.length} 个）</span>
            </div>
            {message.data.sources.map((src, i) => (
              <div key={i} className="flex-gap-4" style={{ fontSize: 11, color: '#555', padding: '2px 0', display: 'flex', alignItems: 'flex-start' }}>
                <span style={{ color: '#52c41a', flexShrink: 0 }}>›</span>
                <span>{src}</span>
              </div>
            ))}
          </div>
        )}

        {/* 合规判断结果卡片（功能三） */}
        {message.data?.type === 'compliance_result' && message.data?.result && (
          <ComplianceCard data={message.data} />
        )}

        {/* 文件差异报告（功能四） */}
        {message.data?.type === 'diff_report' && (
          <DiffReport data={message.data} />
        )}

        {/* 文档生成时参考的知识库来源（template_outline / document） */}
        {!isUser && (message.data?.type === 'template_outline' || message.data?.type === 'document') && message.data?.reference_sources?.length > 0 && (
          <div style={{ marginTop: 8, padding: '7px 10px', background: '#fffbe6', border: '1px solid #ffe58f', borderRadius: 8 }}>
            <div className="flex-gap-4" style={{ fontSize: 11, color: '#d48806', fontWeight: 600, marginBottom: 5, display: 'flex', alignItems: 'center' }}>
              <span>📚</span><span>已参考知识库文档（{message.data.reference_sources.length} 个）</span>
            </div>
            {message.data.reference_sources.map((src, i) => (
              <div key={i} className="flex-gap-4" style={{ fontSize: 11, color: '#555', padding: '2px 0', display: 'flex', alignItems: 'flex-start' }}>
                <span style={{ color: '#d48806', flexShrink: 0 }}>›</span>
                <span>{src}</span>
              </div>
            ))}
          </div>
        )}

        {/* 动作按钮（硬编码，不依赖AI返回actions，确保任何AI模型都能显示） */}
        {!isUser && message.data?.type === 'template_outline' && (
          <div className="flex-gap-8" style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap' }}>
            <Button size="small" type="primary" icon={<CheckCircleOutlined />} style={{ borderRadius: 12 }}
              onClick={() => onAction({ type: 'confirm_outline' }, message)}>确认，生成全文</Button>
            <Button size="small" icon={<ReloadOutlined />} style={{ borderRadius: 12 }}
              onClick={() => onAction({ type: 'regenerate_outline' }, message)}>重新生成大纲</Button>
          </div>
        )}
        {!isUser && message.data?.type === 'document' && message.data?.content && (
          <div className="flex-gap-8" style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap' }}>
            <Button size="small" type="primary" icon={<DownloadOutlined />} style={{ borderRadius: 12 }}
              loading={exporting} onClick={() => onAction({ type: 'download_word' }, message)}>下载Word</Button>
            <Button size="small" icon={<DownloadOutlined />} style={{ borderRadius: 12 }}
              loading={exporting} onClick={() => onAction({ type: 'download_pdf' }, message)}>下载PDF</Button>
            <Button size="small" icon={<EditOutlined />} style={{ borderRadius: 12 }}
              onClick={() => onAction({ type: 'modify' }, message)}>继续修改</Button>
          </div>
        )}
        {!isUser && message.data?.type === 'compliance_result' && message.data?.result && (
          <div className="flex-gap-8" style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap' }}>
            <Button size="small" icon={<DownloadOutlined />} style={{ borderRadius: 12 }}
              loading={exporting} onClick={() => onAction({ type: 'export_report' }, message)}>导出判断书</Button>
            <Button size="small" icon={<EditOutlined />} style={{ borderRadius: 12 }}
              onClick={() => onAction({ type: 'supplement_info' }, message)}>补充材料重新判断</Button>
          </div>
        )}

        {/* 意图标签 */}
        {!isUser && message.intent && message.intent !== 'general_chat' && message.intent !== 'agent' && (
          <div style={{ marginTop: 8 }}>
            <Tag color="blue" style={{ fontSize: 11 }}>
              {
                {
                  template_generate: '模板生成',
                  policy_qa: '政策咨询',
                  compliance_check: '合规判断',
                  file_diff: '文件对比',
                }[message.intent] || message.intent
              }
            </Tag>
          </div>
        )}
      </div>
      {isUser && (
        <Avatar
          icon={<UserOutlined />}
          size={34}
          style={{ background: 'linear-gradient(135deg, #1890ff, #40a9ff)', marginLeft: 10, flexShrink: 0, boxShadow: '0 2px 6px rgba(24,144,255,0.2)' }}
        />
      )}
    </div>
  )
}
