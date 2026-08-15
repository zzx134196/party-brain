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
  sendMessageStream: function (data, onChunk, signal) {
    var token = localStorage.getItem('token')

    function processSSEText(text, onChunk) {
      var lines = text.split('\n')
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i]
        if (line.indexOf('data: ') === 0) {
          try {
            var parsed = JSON.parse(line.slice(6))
            onChunk(parsed)
          } catch (e) { /* ignore */ }
        }
      }
    }

    if (typeof ReadableStream !== 'undefined' && typeof fetch !== 'undefined') {
      return fetch('/api/chat/send/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token,
        },
        body: JSON.stringify(data),
        signal: signal,
      }).then(function (response) {
        if (!response.body || typeof response.body.getReader !== 'function') {
          return response.text().then(function (text) {
            processSSEText(text, onChunk)
          })
        }
        var reader = response.body.getReader()
        var decoder = new TextDecoder()
        var buffer = ''
        function read() {
          return reader.read().then(function (result) {
            if (result.done) return
            buffer += decoder.decode(result.value, { stream: true })
            var lines = buffer.split('\n')
            buffer = lines.pop() || ''
            for (var i = 0; i < lines.length; i++) {
              if (lines[i].indexOf('data: ') === 0) {
                try {
                  var parsed = JSON.parse(lines[i].slice(6))
                  onChunk(parsed)
                } catch (e) { /* ignore */ }
              }
            }
            return read()
          })
        }
        return read()
      }).catch(function (e) {
        if (e && e.name === 'AbortError') return
        throw e
      })
    }

    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest()
      var lastIndex = 0
      xhr.open('POST', '/api/chat/send/stream', true)
      xhr.setRequestHeader('Content-Type', 'application/json')
      xhr.setRequestHeader('Authorization', 'Bearer ' + token)

      if (signal) {
        signal.addEventListener('abort', function () {
          xhr.abort()
        })
      }

      xhr.onprogress = function () {
        var newText = xhr.responseText.substring(lastIndex)
        lastIndex = xhr.responseText.length
        processSSEText(newText, onChunk)
      }

      xhr.onload = function () {
        var remaining = xhr.responseText.substring(lastIndex)
        if (remaining) processSSEText(remaining, onChunk)
        resolve()
      }

      xhr.onerror = function () { reject(new Error('网络请求失败')) }
      xhr.onabort = function () { resolve() }
      xhr.send(JSON.stringify(data))
    })
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
    return api.post('/diff/compare', formData, { timeout: 300000 })
  },
  compareFilesStream: function (file1, file2, onChunk, signal) {
    var token = localStorage.getItem('token')
    var formData = new FormData()
    formData.append('file1', file1)
    formData.append('file2', file2)
    var TIMEOUT_MS = 5 * 60 * 1000  // 5分钟，避免大文件/慢模型被过早中断
    var timedOut = false
    var timeoutId = null
    var controller = null
    var receivedEvent = false
    var receivedDone = false

    function cleanup() {
      if (timeoutId) clearTimeout(timeoutId)
      if (signal) signal.removeEventListener('abort', onExternalAbort)
    }

    function onExternalAbort() {
      if (controller) controller.abort()
      if (typeof xhr !== 'undefined' && xhr) xhr.abort()
    }

    function handleFetchError(e) {
      cleanup()
      if (e && e.name === 'AbortError') {
        if (timedOut) {
          var err = new Error('文件对比处理超时，请稍后重试；若仍超时，请检查文件大小或联系管理员。')
          err.name = 'TimeoutError'
          throw err
        }
        return
      }
      throw e
    }

    function processSSEText(text, onChunk) {
      var lines = text.split('\n')
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i]
        if (line.indexOf('data: ') === 0) {
          try {
            var parsed = JSON.parse(line.slice(6))
            receivedEvent = true
            if (parsed && parsed.done) {
              receivedDone = true
            }
            onChunk(parsed)
          } catch (e) { /* ignore */ }
        }
      }
    }

    if (typeof ReadableStream !== 'undefined' && typeof fetch !== 'undefined') {
      controller = new AbortController()
      if (signal) {
        if (signal.aborted) {
          controller.abort()
        } else {
          signal.addEventListener('abort', onExternalAbort)
        }
      }
      timeoutId = setTimeout(function () {
        timedOut = true
        controller.abort()
      }, TIMEOUT_MS)

      return fetch('/api/diff/compare/stream', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token },
        body: formData,
        signal: controller.signal,
      }).then(function (response) {
        if (!response.body || typeof response.body.getReader !== 'function') {
          return response.text().then(function (text) {
            processSSEText(text, onChunk)
          })
        }
        var reader = response.body.getReader()
        var decoder = new TextDecoder()
        var buffer = ''
        function read() {
          return reader.read().then(function (result) {
            if (result.done) return
            buffer += decoder.decode(result.value, { stream: true })
            var lines = buffer.split('\n')
            buffer = lines.pop() || ''
            for (var i = 0; i < lines.length; i++) {
              if (lines[i].indexOf('data: ') === 0) {
                try {
                  var parsed = JSON.parse(lines[i].slice(6))
                  onChunk(parsed)
                } catch (e) { /* ignore */ }
              }
            }
            return read()
          })
        }
        return read()
      }).then(function () {
        cleanup()
        if (!receivedDone) {
          throw new Error('文件对比流式处理中断，未收到最终结果；请确认后端已更新并查看后端日志')
        }
      }).catch(handleFetchError)
    }

    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest()
      var lastIndex = 0
      xhr.open('POST', '/api/diff/compare/stream', true)
      xhr.setRequestHeader('Authorization', 'Bearer ' + token)
      if (signal) {
        signal.addEventListener('abort', onExternalAbort)
      }
      timeoutId = setTimeout(function () {
        timedOut = true
        xhr.abort()
      }, TIMEOUT_MS)
      xhr.onprogress = function () {
        var newText = xhr.responseText.substring(lastIndex)
        lastIndex = xhr.responseText.length
        processSSEText(newText, onChunk)
      }
      xhr.onload = function () {
        var remaining = xhr.responseText.substring(lastIndex)
        if (remaining) processSSEText(remaining, onChunk)
        cleanup()
        if (receivedDone) {
          resolve()
        } else {
          reject(new Error('文件对比流式处理中断，未收到最终结果；请确认后端已更新并查看后端日志'))
        }
      }
      xhr.onerror = function () { reject(new Error('网络请求失败')) }
      xhr.onabort = function () {
        cleanup()
        if (timedOut) {
          var err = new Error('文件对比处理超时，请稍后重试；若仍超时，请检查文件大小或联系管理员。')
          err.name = 'TimeoutError'
          reject(err)
        } else {
          resolve()
        }
      }
      xhr.send(formData)
    })
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
