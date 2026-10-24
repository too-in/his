# -*- coding: utf-8 -*-
# 本项目仅供个人学习练习，不适合正式业务使用。
# 严禁直接部署于正式生产环境。

"""
HIS 故障知识库系统 - 后端服务
本项目仅供个人学习练习，不适合正式业务使用。
"""

# ===================== 配置区（所有配置项集中放置在代码最顶部） =====================
# AI 服务接口密钥（请替换为你自己的密钥；保留占位符则自动启用 Mock 模式）
API_KEY = "sk-your-ai-api-key-here"
# AI 服务接口地址（兼容 OpenAI 协议的接口）
API_URL = "https://api.siliconflow.cn/v1"
# 使用的 AI 模型名称
MODEL = "deepseek-ai/DeepSeek-V4-Flash"
# 图片上传目录路径
UPLOAD_DIR = "upload"
# SQLite 数据库文件路径
DB_PATH = "his_kb.db"
# 令牌签名密钥（仅用于简易 jwt-like 令牌校验）
TOKEN_SECRET = "his-kb-learning-only-secret"
# 令牌有效期（秒），默认 8 小时
TOKEN_EXPIRE = 8 * 3600
# 允许跨域来源（学习用，按需收紧）
CORS_ORIGINS = ["*"]
# Mock 模式开关：当 API_KEY 仍为占位符时自动启用，返回预设模板供本地学习演示，不消耗 token
AI_MOCK_ENABLED = True
# ==================================================================================

import os
import time
import json
import base64
import hashlib
import hmac
import sqlite3
import secrets
import re
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import bcrypt
import httpx

# 确保上传目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="HIS 故障知识库", description="本项目仅供个人学习练习，不适合正式业务使用。")

# 挂载上传目录为静态文件，用于访问报错截图
app.mount("/upload", StaticFiles(directory=os.path.join(BASE_DIR, UPLOAD_DIR)), name="upload")


@app.get("/", include_in_schema=False)
def root_index():
    """根路径直接返回前端单页"""
    index_path = os.path.join(BASE_DIR, "index.html")
    return FileResponse(index_path, media_type="text/html")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===================== 数据库相关 =====================
def get_db():
    """获取 SQLite 数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库：创建表结构并创建管理员账号"""
    conn = get_db()
    cur = conn.cursor()
    # 用户表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            is_first_login INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    # 故障案例表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            tag TEXT,
            reason TEXT,
            solution TEXT,
            image_path TEXT,
            creator TEXT NOT NULL,
            create_time TEXT NOT NULL
        )
        """
    )
    conn.commit()

    # 检查是否已存在 admin 账号
    cur.execute("SELECT username FROM users WHERE username = ?", ("admin",))
    if cur.fetchone() is None:
        # 仅在初始化函数内部临时使用初始密码，完成哈希后立即丢弃
        init_password = "Admin123"
        password_hash = bcrypt.hashpw(init_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        cur.execute(
            "INSERT INTO users (username, password_hash, is_first_login) VALUES (?, ?, ?)",
            ("admin", password_hash, 1),
        )
        conn.commit()
        # 临时变量在此函数作用域结束即被回收
        init_password = None
    conn.close()


# 应用启动时初始化数据库
@app.on_event("startup")
def on_startup():
    init_db()


# ===================== 令牌相关（简易 jwt-like 格式） =====================
def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(username: str) -> str:
    """生成简易 jwt-like 令牌：header.payload.signature"""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"username": username, "iat": int(time.time()), "exp": int(time.time()) + TOKEN_EXPIRE}
    header_b64 = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(TOKEN_SECRET.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = _b64encode(signature)
    return f"{signing_input}.{sig_b64}"


def verify_token(token: str) -> Optional[str]:
    """校验令牌，成功返回 username，失败返回 None"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(TOKEN_SECRET.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
        provided_sig = _b64decode(sig_b64)
        if not hmac.compare_digest(expected_sig, provided_sig):
            return None
        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload.get("username")
    except Exception:
        return None


def get_current_user(request: Request) -> str:
    """依赖项：从请求头或查询参数中获取令牌并校验"""
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="未提供身份令牌，请先登录")
    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="身份令牌无效或已过期，请重新登录")
    return username


# ===================== 请求模型 =====================
class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    username: str
    old_password: str
    new_password: str


class AIAnalyzeRequest(BaseModel):
    keyword: str


# ===================== AI 系统提示词 =====================
AI_SYSTEM_PROMPT = """你是内部HIS运维故障分析助手，输出内容仅作为个人学习参考，不能替代真实生产运维操作。
业务范围限定：HIS系统、药品归类字典维护、日志查询、网络排查、远机位远程操作、系统部署、门诊药房住院模块故障。

响应规则：
1. 禁止编造数据库表名、字段、药品编码、医院内部配置参数，对不清楚的信息需如实说明，严禁虚构内容。
2. 当涉及修改数据库、底层业务字典、数据变更等操作时，必须强制输出：【重要高危提醒】该操作属于高危，禁止擅自修改数据库，必须走内部审批流程处理。
3. 严格遵循固定输出格式：
【故障现象复述】
【参考故障原因】
【建议排查步骤】
【参考解决方案】
【风险提醒】
4. 信息不足时，需主动引导用户补充：完整报错文字、业务模块、是否有报错截图等关键信息。
5. 明确拒绝回答临床诊疗、用药相关的医学问题。
6. 禁止生成可以直接在生产环境执行的SQL语句。

输出格式要求：仅使用普通文本，采用简单换行，禁止使用markdown格式、代码块及多余客套话。"""


# ===================== 接口：登录 =====================
@app.post("/api/login")
def api_login(req: LoginRequest):
    username = req.username.strip()
    password = req.password
    if not username or not password:
        return JSONResponse(status_code=400, content={"detail": "用户名和密码不能为空"})
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, password_hash, is_first_login FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return JSONResponse(status_code=401, content={"detail": "用户名或密码错误"})
    # 使用 bcrypt 算法对输入密码进行哈希比对验证
    try:
        if not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
            return JSONResponse(status_code=401, content={"detail": "用户名或密码错误"})
    except Exception:
        return JSONResponse(status_code=401, content={"detail": "密码校验失败"})
    token = create_token(username)
    is_first = bool(row["is_first_login"])
    return {
        "token": token,
        "username": username,
        "is_first_login": is_first,
        "message": "登录成功",
    }


# ===================== 接口：修改密码 =====================
@app.post("/api/change_password")
def api_change_password(req: ChangePasswordRequest):
    username = req.username.strip()
    old_password = req.old_password
    new_password = req.new_password
    if not username or not old_password or not new_password:
        return JSONResponse(status_code=400, content={"detail": "参数不能为空"})
    if len(new_password) < 6:
        return JSONResponse(status_code=400, content={"detail": "新密码长度不能少于6位"})
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, password_hash FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return JSONResponse(status_code=404, content={"detail": "用户不存在"})
    # 验证旧密码有效性
    try:
        if not bcrypt.checkpw(old_password.encode("utf-8"), row["password_hash"].encode("utf-8")):
            conn.close()
            return JSONResponse(status_code=401, content={"detail": "旧密码错误"})
    except Exception:
        conn.close()
        return JSONResponse(status_code=401, content={"detail": "旧密码校验失败"})
    new_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cur.execute(
        "UPDATE users SET password_hash = ?, is_first_login = 0 WHERE username = ?",
        (new_hash, username),
    )
    conn.commit()
    conn.close()
    # 修改密码后重新生成令牌
    token = create_token(username)
    return {
        "message": "密码修改成功",
        "token": token,
        "username": username,
        "is_first_login": False,
    }


# ===================== 接口：登出（前端清理 localStorage 即可，后端留接口做记录） =====================
@app.post("/api/logout")
def api_logout(user: str = Depends(get_current_user)):
    return {"message": "已登出"}


# ===================== 接口：获取当前用户信息 =====================
@app.get("/api/me")
def api_me(user: str = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, is_first_login FROM users WHERE username = ?", (user,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"username": row["username"], "is_first_login": bool(row["is_first_login"])}


# ===================== 接口：新增故障案例 =====================
@app.post("/api/cases")
async def api_create_case(
    title: str = Form(...),
    tag: str = Form(""),
    reason: str = Form(""),
    solution: str = Form(""),
    image: Optional[UploadFile] = File(None),
    user: str = Depends(get_current_user),
):
    if not title.strip():
        return JSONResponse(status_code=400, content={"detail": "标题不能为空"})
    image_path = ""
    if image is not None and image.filename:
        # 仅允许图片类型
        allowed_ext = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
        ext = os.path.splitext(image.filename)[1].lower()
        if ext not in allowed_ext:
            return JSONResponse(status_code=400, content={"detail": "仅支持 png/jpg/jpeg/gif/bmp/webp 图片"})
        # 生成安全的文件名
        safe_name = secrets.token_hex(8) + ext
        save_path = os.path.join(UPLOAD_DIR, safe_name)
        content = await image.read()
        with open(save_path, "wb") as f:
            f.write(content)
        # 数据库仅存储相对路径
        image_path = f"{UPLOAD_DIR}/{safe_name}"
    create_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cases (title, tag, reason, solution, image_path, creator, create_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (title.strip(), tag.strip(), reason.strip(), solution.strip(), image_path, user, create_time),
    )
    conn.commit()
    case_id = cur.lastrowid
    conn.close()
    return {"message": "案例新增成功", "id": case_id, "image_path": image_path}


# ===================== 接口：案例列表 =====================
@app.get("/api/cases")
def api_list_cases(user: str = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, tag, reason, solution, image_path, creator, create_time FROM cases ORDER BY id DESC"
    )
    rows = cur.fetchall()
    conn.close()
    data = []
    for r in rows:
        data.append(
            {
                "id": r["id"],
                "title": r["title"],
                "tag": r["tag"],
                "reason": r["reason"],
                "solution": r["solution"],
                "image_path": r["image_path"],
                "creator": r["creator"],
                "create_time": r["create_time"],
            }
        )
    return {"cases": data}


# ===================== 接口：删除案例 =====================
@app.delete("/api/cases/{case_id}")
def api_delete_case(case_id: int, user: str = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, image_path FROM cases WHERE id = ?", (case_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return JSONResponse(status_code=404, content={"detail": "案例不存在"})
    # 同时删除关联图片文件
    if row["image_path"]:
        try:
            if os.path.exists(row["image_path"]):
                os.remove(row["image_path"])
        except Exception:
            pass
    cur.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    conn.commit()
    conn.close()
    return {"message": "案例已删除"}


# ===================== 接口：全文搜索（本地 SQLite 模糊查询） =====================
@app.get("/api/search")
def api_search(keyword: str, user: str = Depends(get_current_user)):
    keyword = keyword.strip()
    if not keyword:
        return {"cases": [], "message": "关键词为空"}
    like = f"%{keyword}%"
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, tag, reason, solution, image_path, creator, create_time
        FROM cases
        WHERE title LIKE ? OR tag LIKE ? OR reason LIKE ? OR solution LIKE ?
        ORDER BY id DESC
        """,
        (like, like, like, like),
    )
    rows = cur.fetchall()
    conn.close()
    data = []
    for r in rows:
        data.append(
            {
                "id": r["id"],
                "title": r["title"],
                "tag": r["tag"],
                "reason": r["reason"],
                "solution": r["solution"],
                "image_path": r["image_path"],
                "creator": r["creator"],
                "create_time": r["create_time"],
            }
        )
    return {"cases": data, "count": len(data)}


# ===================== 接口：AI 故障分析（仅在用户点击按钮时调用） =====================
@app.post("/api/ai_analyze")
def api_ai_analyze(req: AIAnalyzeRequest, user: str = Depends(get_current_user)):
    keyword = req.keyword.strip()
    if not keyword:
        return JSONResponse(status_code=400, content={"detail": "关键词不能为空"})

    # ===== Mock 模式：当 API_KEY 为占位符或 AI_MOCK_ENABLED 打开时，返回预设模板，不消耗 token =====
    is_placeholder = API_KEY.startswith("sk-your-ai-api-key") or not API_KEY.strip()
    if AI_MOCK_ENABLED and is_placeholder:
        mock_text = _build_mock_result(keyword)
        return {
            "result": mock_text,
            "keyword": keyword,
            "mock": True,
            "message": "Mock 模式：当前未配置真实 AI 密钥，返回的是预设模板（仅供本地学习演示，不消耗 token）。",
        }
    # ============================================================================================

    # 构造请求体
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": f"故障关键词或现象描述：{keyword}\n请按固定格式输出分析结果。"},
        ],
        "temperature": 0.3,
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{API_URL.rstrip('/')}/chat/completions", headers=headers, json=payload)
        if resp.status_code != 200:
            return JSONResponse(
                status_code=502,
                content={"detail": f"AI 服务返回错误：HTTP {resp.status_code}", "body": resp.text[:500]},
            )
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return JSONResponse(status_code=502, content={"detail": "AI 服务未返回内容"})
        content = choices[0].get("message", {}).get("content", "")
        return {"result": content, "keyword": keyword, "mock": False}
    except httpx.RequestError as e:
        return JSONResponse(status_code=502, content={"detail": f"调用 AI 服务网络异常：{e}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"AI 分析异常：{e}"})


# ===================== AI 对话框（多轮聊天） =====================
class AIChatMessage(BaseModel):
    role: str
    content: str


class AIChatRequest(BaseModel):
    messages: list[AIChatMessage]


# 对话用系统提示词：保留安全规则，采用自然对话风格（不再强制五段固定格式）
AI_CHAT_SYSTEM_PROMPT = """你是内部HIS运维助手"小智"，与用户进行多轮对话交流，输出内容仅作为个人学习参考，不能替代真实生产运维操作。
业务范围限定：HIS系统、药品归类字典维护、日志查询、网络排查、远机位远程操作、系统部署、门诊药房住院模块故障。

响应规则：
1. 禁止编造数据库表名、字段、药品编码、医院内部配置参数，对不清楚的信息需如实说明，严禁虚构内容。
2. 当涉及修改数据库、底层业务字典、数据变更等操作时，必须提醒：【重要高危提醒】该操作属于高危，禁止擅自修改数据库，必须走内部审批流程处理。
3. 信息不足时，主动引导用户补充：完整报错文字、业务模块、是否有报错截图等关键信息。
4. 明确拒绝回答临床诊疗、用药相关的医学问题。
5. 禁止生成可以直接在生产环境执行的SQL语句。
6. 回答保持简洁实用，符合运维排查场景的自然对话风格。"""


@app.post("/api/ai_chat")
def api_ai_chat(req: AIChatRequest, user: str = Depends(get_current_user)):
    # 校验消息列表
    msgs = []
    for m in req.messages:
        content = (m.content or "").strip()
        if not content:
            continue
        role = m.role if m.role in ("user", "assistant") else "user"
        msgs.append({"role": role, "content": content})
    if not msgs or msgs[-1]["role"] != "user":
        return JSONResponse(status_code=400, content={"detail": "消息不能为空"})
    # 限制上下文长度（最多保留最近 20 条，防止 token 超限）
    msgs = msgs[-20:]

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": AI_CHAT_SYSTEM_PROMPT}] + msgs,
        "temperature": 0.5,
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{API_URL.rstrip('/')}/chat/completions", headers=headers, json=payload)
        if resp.status_code != 200:
            return JSONResponse(
                status_code=502,
                content={"detail": f"AI 服务返回错误：HTTP {resp.status_code}", "body": resp.text[:500]},
            )
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return JSONResponse(status_code=502, content={"detail": "AI 服务未返回内容"})
        content = choices[0].get("message", {}).get("content", "")
        return {"reply": content}
    except httpx.RequestError as e:
        return JSONResponse(status_code=502, content={"detail": f"调用 AI 服务网络异常：{e}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"AI 对话异常：{e}"})


def _build_mock_result(keyword: str) -> str:
    """生成符合系统提示词固定格式的 Mock 模板"""
    return (
        f"【故障现象复述】\n"
        f"根据用户描述的关键词「{keyword}」，初步理解为 HIS 相关故障现象。"
        f"由于当前处于 Mock 模式，以下内容为预设学习模板，仅供参考。\n\n"
        f"【参考故障原因】\n"
        f"1. 业务模块与药品字典数据不一致或字典未及时同步。\n"
        f"2. 接口服务异常或网络连接中断。\n"
        f"3. 数据库连接池耗尽或锁表导致响应超时。\n"
        f"4. 客户端缓存未刷新或权限配置变更未生效。\n\n"
        f"【建议排查步骤】\n"
        f"1. 先收集完整报错文字、业务模块名称、是否有报错截图。\n"
        f"2. 查看对应服务日志，定位异常发生时间段与堆栈信息。\n"
        f"3. 核对相关药品字典、配置参数是否近期变更。\n"
        f"4. 检查网络连通性与接口响应耗时。\n"
        f"5. 必要时联系业务人员确认最近操作行为。\n\n"
        f"【参考解决方案】\n"
        f"1. 如为字典不一致：按内部审批流程同步字典，禁止直接改库。\n"
        f"2. 如为服务异常：重启相关服务并观察日志。\n"
        f"3. 如为数据库锁表：由 DBA 排查并按流程处理。\n"
        f"4. 如为客户端缓存问题：清理缓存或重新登录验证。\n\n"
        f"【风险提醒】\n"
        f"【重要高危提醒】该操作属于高危，禁止擅自修改数据库，必须走内部审批流程处理。\n"
        f"本内容仅为个人学习参考，不能替代真实生产运维操作。"
    )


# ===================== 启动说明 =====================
# 启动命令示例（host 必须为 0.0.0.0 以允许局域网访问）：
#   uvicorn main:app --host 0.0.0.0 --port 8000
#   或直接运行：python main.py
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
