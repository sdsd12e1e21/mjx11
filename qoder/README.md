# 续学 StudyRelay

会记住进度的复习助手。基于 PowerContext 本地记忆服务，为学习与科研场景提供持久化复习进度、薄弱点优先排程、可解释学习规划。

## 公开项目网站

https://studyrelay-3qtjlmas0ke.qoder.zone

由 Qoder Sites 发布，已验证无需登录即可访问。网站展示项目、合成样例、真实运行截图和开发记录；实际复习与记忆功能按本文说明在本地运行。发布与匿名访问检查凭证见 `evidence/PUBLICATION.json`。

## 功能概览

- **学习空间**：两个合成演示用户 + 支持自定义添加，每个空间对应独立 PowerContext Scope
- **偏好设置**：每日复习分钟数（5-120）和学习目标，显式保存后写入 PowerContext Atomic Memory
- **复习卡片**：12 张内置卡片（数据库基础 + 科研方法），支持"需加强"/"已掌握"自评
- **智能排程**：需加强卡片优先，已掌握卡片延后 3 天，逻辑确定可解释
- **记忆引用**：展示每次写入/召回的 artifact_id、revision、scope 和请求耗时
- **数据导出**：JSON 或 Markdown 格式，包含真实记忆引用，不含 token
- **展示网站**：独立静态站点，用于项目介绍和演示

## 技术架构

| 层 | 技术 | 说明 |
|---|------|------|
| 后端 | FastAPI + httpx | Python 3.11+，同源提供 API 和静态文件 |
| 前端 | 原生 HTML/CSS/JS | 无框架依赖，移动端适配 |
| 持久化 | PowerContext 1.5.0 | SQLite 本地服务，Atomic Memory |
| 排程 | 应用本地逻辑 | 确定性规则，不依赖模型 |

### PowerContext 分工

- **Scope**：每个学习空间一个独立 Scope，幂等键保证重启后复用
- **Atomic Memory (kind: study-preferences)**：存储学习偏好 JSON
- **Atomic Memory (kind: study-record)**：存储每次学习记录 JSON
- **写入**：`POST /v1/memory/remember`
- **读取**：`POST /v1/atomic-memory/list`
- **搜索**：`POST /v1/atomic-memory/search`

## 安装

### 前置条件

- Python 3.12+（已验证 3.12）
- PowerContext Server 1.5.0
- Windows 10/11 或 POSIX 系统

### 安装依赖

```bash
# 建议先用 Python 3.12 创建并激活虚拟环境，避免误用系统中的旧 Python：
# Windows PowerShell: python -m venv .venv; .\.venv\Scripts\Activate.ps1
# POSIX: python3.12 -m venv .venv; source .venv/bin/activate
# 1. 安装 PowerContext（如果尚未安装）
# 使用独立环境：
# cd /path/to/qoder-runtime
# pip install "powercontext[cli,server]==1.5.0"

# 2. 安装应用依赖
cd qoder
pip install -r requirements.txt
```

## 运行

### 快速启动

```bash
# Windows PowerShell
.\start.ps1

# POSIX (bash/zsh)
chmod +x start.sh
./start.sh
```

启动脚本会自动：
1. 创建 `.data/powercontext` 数据目录
2. 启动 PowerContext Server（如果未运行）
3. 等待 Server 就绪
4. 启动 StudyRelay 应用
5. 退出时清理自有子进程

### 手动启动

Windows PowerShell（激活虚拟环境后）：

```powershell
# 终端 1，在 qoder 目录中
$env:POWERCONTEXT_HOME = Join-Path (Get-Location) '.data/powercontext'
powercontext server run --host 127.0.0.1 --port 18000 --no-env-file
# 终端 2，在 qoder 目录中
$env:POWERCONTEXT_URL = 'http://127.0.0.1:18000'
python -m uvicorn app.main:app --host 127.0.0.1 --port 18080
```

POSIX（激活虚拟环境后）：

```bash
# 终端 1，在 qoder 目录中
export POWERCONTEXT_HOME="$PWD/.data/powercontext"
powercontext server run --host 127.0.0.1 --port 18000 --no-env-file
# 终端 2，在 qoder 目录中
export POWERCONTEXT_URL=http://127.0.0.1:18000
python -m uvicorn app.main:app --host 127.0.0.1 --port 18080
```

### 访问

打开浏览器访问 http://127.0.0.1:18080

展示网站：http://127.0.0.1:18080/showcase

## 测试

```bash
# 单元测试（不需要 PowerContext Server）
pytest tests/test_scheduler.py tests/test_validation.py -v

# 集成测试（需要 PowerContext Server 运行）
pytest tests/integration/ -v
```

## 项目结构

```
qoder/
├── app/                    # 后端应用
│   ├── __init__.py
│   ├── main.py            # FastAPI 应用入口
│   ├── models.py          # 数据模型
│   ├── cards.py           # 内置复习卡片
│   ├── scheduler.py       # 排程逻辑
│   └── powercontext_client.py  # PowerContext 客户端
├── static/                # 前端静态文件
│   ├── index.html
│   ├── style.css
│   └── app.js
├── showcase/              # 展示网站
│   ├── index.html
│   ├── showcase.css
│   └── showcase.js
├── tests/                 # 测试
│   ├── test_scheduler.py
│   ├── test_validation.py
│   └── integration/
├── .data/                 # 数据目录（gitignore）
│   └── powercontext/
├── start.ps1              # Windows 启动脚本
├── start.sh               # POSIX 启动脚本
├── requirements.txt       # Python 依赖
├── pyproject.toml         # 项目配置
├── .env.example           # 环境变量示例
├── .gitignore
├── README.md              # 本文件
├── VALIDATION.md          # 验证流程
├── QODER_DEVELOPMENT.md   # 开发记录
└── BUILD_BRIEF.md         # 赛题要求
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `POWERCONTEXT_URL` | `http://127.0.0.1:18000` | PowerContext Server 地址 |
| `POWERCONTEXT_TOKEN` | （空） | Server 鉴权 token（可选） |
| `POWERCONTEXT_HOME` | `.data/powercontext` | PowerContext 数据目录 |
| `APP_PORT` | `18080` | 应用端口 |
| `PC_PORT` | `18000` | PowerContext Server 端口（启动脚本用） |

## 适用范围

- 本机单人学习和复习场景
- 数据库/科研方法等结构化知识复习
- 需要持久化学习进度和薄弱点追踪的场景

## 不适用

- 多用户在线服务（Scope 是数据分区，不是身份认证）
- 需要云端推理或 LLM API 的场景
- 大规模知识库管理

## 未完成项

- 自定义卡片录入界面（当前仅支持内置 12 张卡片）
- 实际截图（展示网站中标记为"待补"）
- 更多导出格式（当前仅 JSON 和 Markdown）
- 移动端 PWA 支持

## 许可证

本项目为 2026 OceanBase 竞赛生态参赛作品。
