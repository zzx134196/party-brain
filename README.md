# 智慧党建助手

面向机关党委的AI智能助手，提供模板生成、知识问答、政策合规判断、文件差异对比等能力。

## 功能模块

| 功能 | 描述 |
|------|------|
| 辅助生成 | 输入关键信息，自动填充模板生成工作计划、活动方案等文档 |
| 知识问答 | 自然语言查询党员信息、数据统计分析（NL2SQL） |
| 政策规则库 | RAG检索政策条款，合规判断并附引用溯源 |
| 文件差异 | 对比文件内容差异，输出差异报告 |

## 技术栈

- **后端**: Python FastAPI
- **前端**: React + Ant Design + ECharts
- **LLM**: Qwen2.5 / DeepSeek（私有化部署）
- **向量库**: Milvus
- **数据库**: MySQL 8.0
- **缓存**: Redis

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
cd party-brain

# 复制环境变量配置
cp backend/.env.example backend/.env
# 编辑 .env 文件，配置数据库、LLM等连接信息
```

### 2. Docker 一键部署

```bash
# 启动所有服务（MySQL + Redis + Milvus + 后端）
docker-compose up -d

# 查看日志
docker-compose logs -f backend
```

### 3. 本地开发

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev
```

### 4. 访问

- 后端API文档: http://localhost:8000/docs
- 前端界面: http://localhost:3000
- 默认管理员: admin / admin123

## 项目结构

```
party-brain/
├── backend/                   # 后端项目
│   ├── app/
│   │   ├── api/               # API路由
│   │   │   ├── auth.py        # 认证接口
│   │   │   ├── chat.py        # 对话接口（核心）
│   │   │   ├── template.py    # 模板管理
│   │   │   ├── member.py      # 党员管理
│   │   │   └── policy.py      # 政策知识库
│   │   ├── core/              # 核心逻辑
│   │   │   ├── llm.py         # LLM调用封装
│   │   │   ├── intent.py      # 意图识别
│   │   │   ├── auth.py        # JWT认证
│   │   │   ├── nl2sql.py      # NL2SQL
│   │   │   ├── template_gen.py# 模板生成
│   │   │   ├── rag.py         # RAG检索
│   │   │   └── compliance.py  # 合规判断
│   │   ├── models/            # 数据模型
│   │   ├── main.py            # 应用入口
│   │   └── config.py          # 配置
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── knowledge/                 # 知识库处理
│   └── pipeline/
│       ├── parser.py          # 文档解析
│       ├── chunker.py         # 文档切片
│       └── embedder.py        # 向量化+存储
├── frontend/                  # 前端项目（React）
├── docker-compose.yml
└── README.md
```

## API 接口概览

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login` | POST | 用户登录 |
| `/api/auth/me` | GET | 当前用户信息 |
| `/api/chat/send` | POST | 发送消息（含意图识别+路由） |
| `/api/chat/send/stream` | POST | 流式发送消息 |
| `/api/chat/conversations` | GET | 对话列表 |
| `/api/templates/` | GET/POST | 模板管理 |
| `/api/members/` | GET | 党员列表 |
| `/api/members/import` | POST | 批量导入党员 |
| `/api/members/stats/*` | GET | 党员统计 |
| `/api/policy/documents/*` | GET/POST/DELETE | 政策文件管理 |
| `/api/policy/stats/*` | GET | 使用统计 |

## 安全说明

- LLM 建议私有化部署，避免党员信息外泄
- 手机号等敏感字段自动脱敏展示
- SQL查询仅允许SELECT，禁止写操作
- 操作日志全记录，支持审计追查
- JWT认证 + 角色权限（admin/user）
