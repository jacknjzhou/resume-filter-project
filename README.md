# 简历审阅系统（Resume Review）

基于私有大模型的自动化简历筛选与评价系统。HR / 招聘负责人提供一个岗位 JD 与多份候选人简历（单次 ≤ 10 份），系统模拟真实 HR 团队的分工方式，通过多角色 LLM 流水线自动完成简历筛选、评分、排序与面试建议。

**核心特性：**

- **多角色流水线**：JD 解析官 → 结构化提取员 → 初筛专员 → 资深面试官 → HR 主管，模拟真人 HR 团队分工
- **多种简历来源**：PDF / Word (docx) / 图片扫描件 / 纯文本粘贴
- **OCR 双通道识别**：PaddleOCR 主通道 + 多模态 LLM 兜底，最大化扫描件识别质量
- **私有化部署**：数据不出内网，通过 OpenAI 兼容接口接入 vLLM / Ollama 部署的 Qwen / GLM 等模型
- **实时进度**：SSE 推送流水线进度（如「简历 3/8：资深面试官评估中」）
- **报告导出**：Markdown / Excel 汇总报告一键导出
- **Docker Compose 一键启动**：Web、API、PostgreSQL、OCR（可选）全栈部署

## 核心输出

- **匹配度评分与排序**：A / B / C 分档 + 四维评分（技能匹配 / 经验匹配 / 稳定性 / 潜力，各 0-100）
- **逐份评价报告**：亮点、风险点、与 JD 差距
- **结构化信息提取**：教育经历、工作经历、技能清单、项目经历、证书
- **面试建议问题**：每位通过初筛的候选人 3-5 个

## 系统架构

```
┌─────────────┐     ┌──────────────────────┐     ┌─────────────┐
│  Web 前端    │────▶│  FastAPI (api 服务)   │────▶│ PostgreSQL   │
│  Vue3+Vite  │ SSE │  - REST API          │     │  (db 服务)   │
│  nginx 托管  │◀────│  - 多角色流水线        │     └─────────────┘
└─────────────┘     │  - 简历解析器          │
                    └──────────┬───────────┘     ┌─────────────┐
                               └────────────────▶│ 私有大模型    │
                                 OpenAI 兼容接口  │ (外部服务，   │
                                                │  配置接入)    │
                                                └─────────────┘
```

### Docker Compose 服务清单

| 服务 | 镜像/构建 | 说明 |
|---|---|---|
| `api` | 本地 Dockerfile（Python 3.11 + FastAPI） | REST API、多角色流水线、简历解析 |
| `web` | nginx:alpine | 托管前端构建产物，反向代理 `/api` 到 api 服务 |
| `db` | postgres:16 | 数据卷 `pgdata` 持久化 |
| `ocr`（可选） | paddlepaddle/paddleocr | 图片/扫描件文字识别，通过 `--profile ocr` 按需启停 |

私有大模型不进 compose，通过环境变量配置（见 [环境变量](#环境变量)）。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11、FastAPI、SQLAlchemy 2.0、pydantic v2、OpenAI SDK |
| 简历解析 | PyMuPDF（PDF）、python-docx（Word）、PaddleOCR + 多模态 LLM（图片） |
| 前端 | Vue 3、Vite、Element Plus、ECharts（雷达图）、vue-router |
| 数据库 | PostgreSQL 16（JSONB 存储评估结果） |
| 部署 | Docker Compose、nginx |
| 测试 | pytest + pytest-asyncio（LLM 全 mock） |

## 项目结构

```
resume-filter-project/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口（ lifespan 自动建表）
│   │   ├── config.py             # pydantic-settings 配置（.env）
│   │   ├── db.py                 # SQLAlchemy 会话与引擎
│   │   ├── models.py             # tasks / resumes / llm_logs 表模型
│   │   ├── schemas.py            # pydantic 输出结构（JD/档案/评分/报告）
│   │   ├── llm.py                # OpenAI 兼容客户端（含重试与健康检查）
│   │   ├── parsers/              # 简历解析器：pdf / docx / image / 文本
│   │   ├── pipeline/
│   │   │   ├── runner.py         # 流水线编排（并发限流、超时、状态流转）
│   │   │   ├── roles.py          # 五个角色的调用封装
│   │   │   └── events.py         # SSE 事件总线
│   │   └── routers/              # tasks.py（任务/导出/SSE）、resumes.py（单人报告）
│   ├── prompts/                  # 各角色提示词模板（改提示词无需改代码）
│   │   ├── jd_analyst.txt        # JD 解析官
│   │   ├── extractor.txt         # 结构化提取员
│   │   ├── screener.txt          # 初筛专员
│   │   ├── interviewer.txt       # 资深面试官
│   │   ├── hr_manager.txt        # HR 主管
│   │   ├── ocr_fallback.txt      # 多模态兜底转录
│   │   └── text_corrector.txt    # OCR 文本校正
│   ├── tests/                    # pytest 全量测试（mock LLM）
│   ├── Dockerfile
│   ├── pytest.ini
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/                # TaskCreate / TaskProgress / TaskResult
│   │   ├── App.vue
│   │   ├── api.js                # 后端 API 封装
│   │   └── main.js
│   ├── Dockerfile                # 多阶段构建 + nginx 托管
│   ├── nginx.conf                # /api 反向代理到 api 服务
│   ├── vite.config.js            # dev 模式 /api 代理到 localhost:8000
│   └── package.json
├── samples/                      # 端到端演示样例
│   ├── jd_sample.txt             # 样例 JD（高级后端开发工程师）
│   ├── 张三_后端.pdf / 李四_后端.docx / 王五_前端.txt
│   ├── make_samples.py           # 样例生成脚本
│   └── mock_llm.py               # 极简 OpenAI 兼容 mock LLM（离线演示）
├── docs/superpowers/             # 设计文档与实施计划
├── docker-compose.yml
└── .gitignore
```

## 快速开始

### 前置条件

- Docker & Docker Compose
- 一个 OpenAI 兼容的大模型服务（vLLM / Ollama 私有部署，或任意兼容网关）

### 1. 配置环境变量

在项目根目录创建 `.env`（已被 `.gitignore` 忽略，不会泄露密钥）：

```bash
# 大模型（必填）
LLM_BASE_URL=http://your-vllm-host:8000/v1   # OpenAI 兼容接口地址
LLM_API_KEY=EMPTY                             # 私有部署可填占位值
LLM_MODEL=qwen2.5-72b-instruct                # 主模型，用于各角色推理与文本校正

# 多模态模型（可选，用于图片 OCR 兜底；不配置则禁用兜底通道）
LLM_VLM_MODEL=qwen-vl

# 数据库（默认值即可，与 compose 一致）
# DATABASE_URL=postgresql+psycopg://resume:resume@db:5432/resume_review

# OCR（启用 ocr profile 时生效）
# OCR_BASE_URL=http://ocr:8866
# OCR_CONFIDENCE_THRESHOLD=0.85
```

### 2. 启动全栈

```bash
docker compose up -d
```

如需处理图片/扫描件简历，附带 OCR 服务一起启动：

```bash
docker compose --profile ocr up -d
```

启动后访问 **http://localhost:8080** 即可使用。

### 3. 跑一次端到端演示（可选）

项目自带样例数据与 mock LLM，可在没有真实大模型的机器上验证全流程：

```bash
# 1. 启动 mock LLM（OpenAI 兼容接口，监听 8000 端口）
uvicorn --app-dir samples mock_llm:app --port 8000

# 2. .env 中将 LLM_BASE_URL 指向 mock
#    LLM_BASE_URL=http://host.docker.internal:8000/v1
#    LLM_MODEL=mock

# 3. 重启 api 服务后，在页面上传 samples/jd_sample.txt
#    以及 samples/ 下的三份样例简历，提交任务即可
```

样例效果：张三/李四（5 年后端）通过初筛并进入评分排序；王五（大专、1 年前端）被初筛淘汰，分档 D。

## 使用流程

1. **任务创建页**：上传/粘贴 JD，拖拽上传简历文件或粘贴简历文本（≤ 10 份），提交后自动跳转进度页
2. **进度页**：每个候选人一行，实时显示所处环节（解析 → 提取 → 初筛 → 面评 → 汇总），SSE 自动刷新
3. **结果页**：左侧排名榜单（A/B/C 分档色标），点击查看单人详情——结构化信息表、四维评分雷达图、亮点/风险/差距、面试建议问题；顶部可导出 Markdown / Excel 报告

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://resume:resume@db:5432/resume_review` | PostgreSQL 连接串 |
| `LLM_BASE_URL` | `http://localhost:8000/v1` | OpenAI 兼容接口地址 |
| `LLM_API_KEY` | `EMPTY` | API Key，私有部署可为占位值 |
| `LLM_MODEL` | `qwen2.5-72b-instruct` | 主模型名（各角色推理 + 文本校正） |
| `LLM_VLM_MODEL` | （空） | 多模态模型名（图片 OCR 兜底）；不配置则禁用兜底通道 |
| `LLM_TIMEOUT` | `120` | LLM 单次调用超时（秒） |
| `OCR_BASE_URL` | `http://ocr:8866` | PaddleOCR 服务地址 |
| `OCR_CONFIDENCE_THRESHOLD` | `0.85` | OCR 合格置信度阈值 |
| `STEP_TIMEOUT` | `120` | 流水线单步超时（秒） |
| `MAX_CONCURRENCY` | `3` | 简历并行处理数（asyncio.Semaphore 限流） |
| `UPLOADS_DIR` | `./uploads` | 简历文件上传目录 |

## API 说明

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查（含 LLM 连通性预检），返回 `{"llm": true/false}` |
| POST | `/api/tasks` | 创建任务（multipart：`jd_file` 或 `jd_text` + `resumes` 文件列表 + `pasted_texts`），校验模型可用性后后台启动流水线 |
| GET | `/api/tasks/{id}` | 任务详情：状态、JD 解析结果、汇总排名与分档、各简历状态 |
| GET | `/api/tasks/{id}/events` | SSE 进度流（任务已结束时立即下发终态事件） |
| GET | `/api/resumes/{id}/report` | 单人完整报告：解析元数据、纯文本、结构化档案、初筛、评估、分档排名 |
| GET | `/api/tasks/{id}/export?format=md\|xlsx` | 导出 Markdown / Excel 汇总报告 |

示例：

```bash
# 健康检查
curl http://localhost:8080/api/health

# 创建任务（JD 文本 + 两份简历文件 + 一段粘贴文本）
curl -X POST http://localhost:8080/api/tasks \
  -F 'jd_text=岗位：高级后端开发工程师...' \
  -F 'resumes=@张三_后端.pdf' \
  -F 'resumes=@李四_后端.docx' \
  -F 'pasted_texts=王五，大专学历，1 年前端经验。'

# 查询任务结果
curl http://localhost:8080/api/tasks/1

# 导出 Excel
curl -o report.xlsx 'http://localhost:8080/api/tasks/1/export?format=xlsx'
```

## 多角色流水线

| 顺序 | 角色 | 提示词 | 输入 | 输出 |
|---|---|---|---|---|
| 1 | JD 解析官 | `prompts/jd_analyst.txt` | JD 原文 | 结构化 JD：职责、硬性要求（含权重）、加分项 |
| 2 | 结构化提取员 | `prompts/extractor.txt` | 简历纯文本 | JSON 档案：教育、工作经历、技能、项目、证书 |
| 3 | 初筛专员 | `prompts/screener.txt` | 结构化 JD + 简历档案 | 硬性条件逐条核对，通过/淘汰 + 逐条理由；**淘汰者止步于此**（分档 D） |
| 4 | 资深面试官 | `prompts/interviewer.txt` | 通过初筛者的档案 + JD | 四维评分（0-100）、亮点、风险点、差距、3-5 个面试问题 |
| 5 | HR 主管 | `prompts/hr_manager.txt` | 全部通过者的评估结果 | 统一排序、A/B/C 分档、最终总结报告 |

编排要点：

- 任务创建后 JD 解析官先执行一次，结果入库供所有简历共享
- 各简历以 `asyncio.Semaphore(MAX_CONCURRENCY)` 限流并行推进
- 每步结果即时写入 PostgreSQL，进度通过 SSE 推送前端
- 所有角色共用同一个 OpenAI 兼容客户端，差异仅在提示词模板——**调整提示词无需改代码**

## 简历解析与 OCR 双通道

| 来源 | 解析方式 |
|---|---|
| PDF | PyMuPDF 提取文本；加密/损坏则记录失败原因标记 `failed`；扫描版（全文不足约 200 字符）自动转图片通道 |
| docx | python-docx 提取文本 |
| 图片/扫描件 | OCR 双通道识别（见下） |
| 纯文本粘贴 | 直接使用 |

**图片识别双通道设计：**

1. **通道 1 — PaddleOCR 主通道**（默认，成本近零）：逐张识别，平均置信度 ≥ `OCR_CONFIDENCE_THRESHOLD`（默认 0.85）且文本量充足视为合格
2. **通道 2 — 多模态 LLM 兜底**（`LLM_VLM_MODEL`）：满足其一即触发——OCR 服务不可用 / 置信度低于阈值 / 疑似乱码（非中英文字符占比 > 30%）；原始图片直接发给多模态模型按版面转录
3. **共用校正步骤**：无论哪个通道产出，均追加一次轻量 LLM 校正（修复形近字、断行、乱码，不改写事实），校正前后文本一并入库便于追溯

## 数据模型

```
tasks        id, jd_raw (TEXT), jd_parsed (JSONB), status,
             summary_report (JSONB), created_at, updated_at
resumes      id, task_id (FK), filename, source_type,
             raw_text (TEXT), parse_meta (JSONB), profile (JSONB),
             screening (JSONB), evaluation (JSONB), final_grade (CHAR),
             final_rank (INT), status, error_message, created_at, updated_at
llm_logs     id, task_id (FK), role, prompt_tokens,
             completion_tokens, duration_ms, created_at
```

- 评估结果全部使用 JSONB 存储，提示词迭代后字段可平滑演化
- 简历 `status` 枚举：`pending / parsing / extracting / screening / evaluating / done / failed / needs_review`
- `llm_logs` 记录每次调用的 token 消耗与耗时（含各角色、`ocr_fallback`、`text_correct`），用于成本观测
- `parse_meta` 记录实际识别通道（`pymupdf / paddleocr / vlm_fallback`）、OCR 置信度、校正前原始文本

## 错误处理

| 场景 | 处理策略 |
|---|---|
| LLM JSON 输出格式错误 | pydantic 校验失败自动重试 2 次（附格式错误说明）；仍失败标记 `needs_review`，不中断任务 |
| PDF 加密/损坏 | 标记 `failed` 并记录原因，不阻塞其他简历 |
| OCR 失败/低置信度/疑似乱码 | 自动触发多模态 LLM 兜底；两通道均失败才标记 `failed` |
| 多模态模型不可用 | 回退使用 OCR 原始文本并标记 `needs_review`，提示人工核对 |
| 模型服务不可用 | 创建任务前连通性预检，失败直接拒绝（HTTP 503） |
| 单步处理超时 | 默认 120s，超时按 `needs_review` 处理 |
| 服务重启 | 重启后非终态任务标记 `failed`，提示重新发起 |

## 本地开发

### 后端

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 需要本地 PostgreSQL，或直接用 compose 只起数据库
docker compose up -d db

# 配置 .env 后启动（或用 mock LLM）
uvicorn app.main:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev        # dev 模式下 /api 自动代理到 localhost:8000
npm run build      # 构建产物由 nginx 托管（Dockerfile 多阶段构建）
```

### 测试

```bash
cd backend
pytest             # 全部测试使用 aiosqlite + mock LLM，无需真实数据库与模型
```

测试覆盖：流水线编排（状态流转、并发限流、失败重试、淘汰短路）、各格式解析器（含损坏文件）、OCR 双通道切换、API 契约、配置加载、schema 校验。

## 常见问题

**Q：必须用私有部署的模型吗？**
系统只要求 OpenAI 兼容接口，理论上任何兼容网关均可。私有化部署是为了满足「简历数据不出内网」的合规要求，请按实际合规政策选择。

**Q：不配置 `LLM_VLM_MODEL` 会怎样？**
图片简历仅走 PaddleOCR 主通道，OCR 不合格时直接标记 `needs_review`，提示人工核对，不会中断任务。

**Q：单次最多几份简历？**
10 份（服务端硬校验，超出返回 HTTP 422）。更大规模可后续将 asyncio 并发平移到 Celery 队列。

**Q：如何调整各角色的行为？**
直接编辑 `backend/prompts/` 下对应的提示词模板即可，无需改代码、无需重启（提示词在每次调用时读取）。

## 范围外（YAGNI）

- 不做用户账号体系与多租户（单团队内部使用）
- 不做千份级大规模任务队列
- 不做在线简历编辑或简历库长期沉淀
- 不做移动端适配
