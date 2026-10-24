# HIS 故障知识库系统（个人学习练习）

> **安全提示：本项目仅供个人学习练习，不适合正式业务使用。严禁直接部署于正式生产环境。**

一套前后端完全分离、可交互的 HIS（医院信息系统）故障知识库系统，仅用于个人学习与练习。

---

## 一、技术栈

| 模块     | 技术                                  |
| -------- | ------------------------------------- |
| 后端     | Python + FastAPI（仅提供 JSON 接口）   |
| 前端     | 原生 HTML + JavaScript（单文件）      |
| 数据库   | SQLite                                |
| 密码加密 | bcrypt                                |
| AI 接口  | 兼容 OpenAI 协议（可按需替换地址）    |

---

## 二、目录结构

```
his/
├── main.py            # 后端 FastAPI 应用（含配置区在顶部）
├── index.html         # 前端单页应用
├── requirements.txt   # Python 依赖
├── README.md          # 本文档
├── HIS_KB.spec        # PyInstaller 打包配置（生成 exe 用）
├── his_kb.db          # SQLite 数据库（首次运行自动生成）
├── upload/            # 报错截图上传目录（首次运行自动生成）
├── build/             # PyInstaller 构建中间产物（可删除）
└── dist/
    └── HIS_KB.exe     # 打包产物：免安装单文件版（发给对方即可运行）
```

---

## 三、安装与启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

`requirements.txt` 内容：

```
fastapi
uvicorn[standard]
bcrypt
httpx
python-multipart
```

### 2. 配置 AI 接口

打开 `main.py`，在文件**最顶部配置区**修改：

```python
API_KEY = "sk-your-ai-api-key-here"        # 你的 AI 服务密钥（保留占位符则自动启用 Mock 模式）
API_URL = "https://api.siliconflow.cn/v1"  # 兼容 OpenAI 协议的接口地址
MODEL = "deepseek-ai/DeepSeek-V4-Flash"    # 模型名称
UPLOAD_DIR = "upload"                      # 截图上传目录
DB_PATH = "his_kb.db"                      # SQLite 数据库文件
AI_MOCK_ENABLED = True                     # Mock 模式开关
```

> **Mock 模式说明**：当 `API_KEY` 仍为占位符 `sk-your-ai-api-key-here` 且 `AI_MOCK_ENABLED=True` 时，`/api/ai_analyze` 会**自动返回预设模板**（符合系统提示词固定五段格式），**不消耗 token**，方便本地学习演示。
> 当你填入真实密钥后，Mock 模式会自动失效，转而调用真实 AI 服务。

> 配置区只包含 API_KEY、API_URL、MODEL、UPLOAD_DIR 等必要项，**严禁在配置区定义明文密码**；管理员初始密码仅在 `init_db()` 函数内部临时使用，完成哈希后立即丢弃。

### 3. 启动后端

```bash
# 方式一（推荐）
uvicorn main:app --host 0.0.0.0 --port 8000

# 方式二：自动寻找 8000-8010 中的空闲端口启动
python main.py
```

> `host="0.0.0.0"` 用于允许局域网内其它设备访问；`python main.py` 启动时若 8000 端口被占用，会自动尝试 8001-8010，以控制台实际输出的端口为准。

### 4. 访问前端

前端页面由后端直接托管，启动后用浏览器打开：

```
http://127.0.0.1:8000
```

无需单独启动前端，也**不要直接双击 index.html**（`file://` 协议下接口请求会失败）。`index.html` 中 `API_BASE` 保持为空即可（前后端同源），仅当前后端分开部署时才需要改为后端完整地址。

---

## 四、打包为 exe 分发给别人（免安装）

对方**无需安装 Python**，只需一个 exe 文件即可运行测试。

### 1. 打包（开发者操作）

在 `his` 目录下执行：

```bash
pip install pyinstaller

python -m PyInstaller --onefile --add-data "index.html;." --name HIS_KB main.py --noconfirm --exclude-module matplotlib --exclude-module IPython --exclude-module PIL --exclude-module pygame --exclude-module tkinter --exclude-module jinja2 --exclude-module pytest --exclude-module numpy --exclude-module pandas --exclude-module torch --exclude-module cv2 --exclude-module pygments --exclude-module chardet --exclude-module dateutil --exclude-module distutils
```

- 产物：`dist/HIS_KB.exe`（约 16 MB）
- `--exclude-module` 列表用于剔除被误收集的无关重型库，显著减小体积
- 修改代码后重新打包：`python -m PyInstaller HIS_KB.spec --noconfirm`
- 如需自定义图标：追加 `--icon=xxx.ico`

### 2. 发送前清理

`his_kb.db` 与 `upload/` 是运行时自动生成的，**不要随 exe 一起发送**（数据库里可能存有你改过的密码和测试数据）。只发 `dist/HIS_KB.exe` 一个文件即可。

### 3. 对方使用步骤（零门槛）

1. 双击 `HIS_KB.exe`，会弹出黑色控制台窗口——这就是服务本体，**最小化即可，不能关闭**，关掉窗口即停止服务。
2. 浏览器打开 `http://127.0.0.1:8000`；若 8000 被占用，程序会自动尝试 8001-8010，以控制台窗口提示的端口为准。
3. 使用 `admin / Admin123` 登录，首次登录强制修改密码。
4. 数据库 `his_kb.db` 与截图目录 `upload/` 自动生成在 exe 同目录；AI 功能自动处于 Mock 模式，无需配置密钥。
5. 删除 exe 及同目录生成的文件即可完全卸载。

> 注意：exe 为 Windows 单文件版，首次启动需解压到临时目录，耗时几秒属正常现象。exe 内置的数据库为全新状态，与开发机上的 `his_kb.db` 互不相干。

---

## 五、默认账号

| 用户名 | 初始密码   | 说明                       |
| ------ | ---------- | -------------------------- |
| admin  | Admin123   | 首次登录强制修改密码       |

> 首次以 admin 登录时，`is_first_login=1`，系统会**强制弹出修改密码弹窗**，必须完成修改后才能进入主业务页；改密成功后该字段置为 0，后续登录不再强制改密。其它账号无此限制。

---

## 六、功能说明

### 6.1 账号与登录

- 登录接口：`POST /api/login`，使用 bcrypt 对输入密码做哈希比对。
- 身份令牌：登录成功后生成简易 jwt-like 令牌，前端用 `localStorage` 保存。
- 权限控制：所有业务接口校验令牌，未授权返回 `401`。
- 强制改密：admin 首次登录拦截 + 改密接口 `POST /api/change_password`（校验旧密码 → 更新哈希 → `is_first_login=0`）。
- 登出：前端清理 `localStorage`，并调用 `POST /api/logout`。

### 6.2 故障案例管理

- 新增案例（`POST /api/cases`，`multipart/form-data`）：
  - 字段：标题、标签、故障原因、解决方案、报错截图。
  - 截图保存到 `upload/`，数据库只存相对路径。
  - 自动记录提交人 `username` 和创建时间。
- 案例列表（`GET /api/cases`）：展示缩略图、标题、标签、原因摘要、方案摘要、提交人、时间，并支持删除。
- 删除案例（`DELETE /api/cases/{id}`）：前端弹出 `confirm` 确认对话框，后端同步删除图片文件。

### 6.3 全文搜索

- 接口：`GET /api/search?keyword=xxx`
- 基于 SQLite `LIKE` 模糊查询，覆盖标题、标签、故障原因、解决方案。
- 纯本地检索，**不依赖外部 API，不消耗 token**。

### 6.4 AI 故障分析

- **优先级**：用户输入搜索词时，前端**先调用本地搜索**。
- **无结果处理**：本地无匹配时，展示「未找到匹配的本地故障案例」并渲染按钮 `🤖 调用 AI 故障分析（会消耗 token）`。
- **资源保护**：**未点击按钮绝不调用 AI 接口**，节约 token。
- 接口：`POST /api/ai_analyze`，`{ "keyword": "..." }`。
- 结果展示区**保留换行格式**，使用 `white-space: pre-wrap`。

---

## 七、AI 系统提示词要点

`main.py` 中 `AI_SYSTEM_PROMPT` 已包含：

- 角色：内部 HIS 运维故障分析助手，输出仅供个人学习参考。
- 业务范围：HIS 系统、药品归类字典维护、日志查询、网络排查、远机位远程操作、系统部署、门诊药房 / 住院模块故障。
- 禁止编造数据库表名、字段、药品编码、医院内部参数。
- 涉及数据库 / 字典 / 数据变更必须输出：`【重要高危提醒】该操作属于高危，禁止擅自修改数据库，必须走内部审批流程处理。`
- 固定输出格式：`【故障现象复述】【参考故障原因】【建议排查步骤】【参考解决方案】【风险提醒】`。
- 信息不足时主动引导补充：完整报错文字、业务模块、是否有报错截图。
- 拒绝临床诊疗 / 用药相关医学问题。
- 禁止生成可直接在生产环境执行的 SQL。
- 仅输出普通文本换行，禁止 markdown / 代码块。

---

## 八、接口一览

| 方法   | 路径                    | 说明                 | 鉴权 |
| ------ | ----------------------- | -------------------- | ---- |
| POST   | /api/login              | 登录                 | 否   |
| POST   | /api/change_password    | 修改密码             | 否   |
| POST   | /api/logout             | 登出                 | 是   |
| GET    | /api/me                 | 当前用户信息         | 是   |
| POST   | /api/cases              | 新增案例             | 是   |
| GET    | /api/cases              | 案例列表             | 是   |
| DELETE | /api/cases/{id}         | 删除案例             | 是   |
| GET    | /api/search?keyword=    | 全文搜索             | 是   |
| POST   | /api/ai_analyze         | AI 故障分析（按需）  | 是   |

---

## 九、安全与使用须知

1. 本项目**仅供个人学习练习**，不适合正式业务使用。
2. 密码使用 bcrypt 哈希存储，**数据库中不保存任何明文密码**。
3. 令牌为简易 jwt-like 实现，未引入复杂 OAuth，符合内网学习工具的简洁性要求。
4. AI 接口仅在用户**手动点击按钮**时调用，避免无谓 token 消耗。
5. 请勿在生产环境使用默认密钥、默认账号与默认令牌密钥。
