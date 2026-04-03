import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

// 请求拦截器 - 添加Token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器 - 处理认证失败
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// 认证
export const authApi = {
  login: (username, password) =>
    api.post('/auth/login', new URLSearchParams({ username, password })),
  getMe: () => api.get('/auth/me'),
  listUsers: () => api.get('/auth/users'),
  createUser: (data) => api.post('/auth/register', data),
  updateUser: (id, data) => api.put(`/auth/users/${id}`, data),
  deleteUser: (id) => api.delete(`/auth/users/${id}`),
  importUsers: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/auth/users/import', fd)
  },
}

// 对话
export const chatApi = {
  getConversations: () => api.get('/chat/conversations'),
  deleteConversation: (id) => api.delete(`/chat/conversations/${id}`),
  getMessages: (conversationId) => api.get(`/chat/conversations/${conversationId}/messages`),
  sendMessage: (data) => api.post('/chat/send', data),
  // 流式请求需要特殊处理（支持 signal 取消）
  sendMessageStream: async (data, onChunk, signal) => {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/chat/send/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
      signal,
    })
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              onChunk(data)
            } catch (e) { /* ignore */ }
          }
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') return // 用户主动停止
      throw e
    }
  },
  // 上传聊天附件（提取文本）
  uploadAttachment: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/chat/upload-attachment', fd, { timeout: 30000 })
  },
}

// 模板
export const templateApi = {
  list: (category) => api.get('/templates/', { params: { category } }),
  get: (id) => api.get(`/templates/${id}`),
  create: (data) => api.post('/templates/', data),
  update: (id, data) => api.put(`/templates/${id}`, data),
  delete: (id) => api.delete(`/templates/${id}`),
}

// 政策知识库
export const policyApi = {
  listDocuments: () => api.get('/policy/documents'),
  uploadDocument: (file, title) => {
    const formData = new FormData()
    formData.append('file', file)
    if (title) formData.append('title', title)
    return api.post('/policy/documents/upload', formData)
  },
  uploadDocumentsBatch: (files) => {
    const formData = new FormData()
    files.forEach((f) => formData.append('files', f))
    return api.post('/policy/batch-upload', formData)
  },
  processDocument: (id) => api.post(`/policy/documents/${id}/process`),
  batchProcess: (docIds) => api.post('/policy/documents/batch-process', docIds || []),
  batchDelete: (docIds) => api.post('/policy/documents/batch-delete', docIds),
  getChunks: (id) => api.get(`/policy/documents/${id}/chunks`),
  deactivateDocument: (id) => api.put(`/policy/documents/${id}/deactivate`),
  deleteDocument: (id) => api.delete(`/policy/documents/${id}`),
}

// 文件差异对比
export const diffApi = {
  compareFiles: (file1, file2) => {
    const formData = new FormData()
    formData.append('file1', file1)
    formData.append('file2', file2)
    return api.post('/diff/compare', formData, { timeout: 120000 })
  },
}

// 系统设置
export const settingsApi = {
  getLLMConfig: () => api.get('/settings/llm'),
  updateLLMConfig: (data) => api.put('/settings/llm', data),
  testLLMConnection: (data) => api.post('/settings/llm/test', data),
  getEmbeddingConfig: () => api.get('/settings/embedding'),
  updateEmbeddingConfig: (data) => api.put('/settings/embedding', data),
  getOverview: () => api.get('/settings/overview'),
}

export default api
