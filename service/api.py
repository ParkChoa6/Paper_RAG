"""FastAPI 路由 —— 前后端之间的那条线。

── 流水线里的位置 ──

    浏览器 ──▶ Streamlit（service/ui.py）
                    │  HTTP
                    ▼
              FastAPI（本文件）──▶ Runtime ──▶ paper_rag.pipeline.ask()
                                                  │
                                                  └─ 检索 / 生成 / 引用校验

    ★ 界面【不 import paper_rag】。它只认识 JSON。
      这样"前端"才有资格叫前端：换掉 Streamlit，后端一行不用动。

── 产品 / 外壳 ──

    本文件是【外壳】：解析参数、调 runtime、把结果拼成 JSON、记日志。
    它做不了的判断一律不做 —— 特别是这几件，全都留在 pipeline / cite 里：
        · 什么时候算 answered / refused / suspect / parse_failed
        · problems 里报几条、报什么
        · 编号要不要修正
    外壳只负责【如实转述】。转述时漏掉字段，比报错更难查。

启动:
    ./.venv/Scripts/python.exe -m uvicorn service.api:app --port 8000
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from paper_rag.config import EVAL_DIR, EXPAND_ENABLED, TOP_K
from service.runtime import Runtime

logger = logging.getLogger(__name__)

# ★ 关掉 httpx 的 INFO 噪音。
#   ollama 的客户端走 httpx，它会给【每一次】/api/embed、/api/generate 打一行
#   "HTTP Request: POST ... 200 OK"。我们要的是【一次问答一行】，
#   而不是一次问答三行、其中两行是传输层。
#   注意只压 httpx：uvicorn 自己的访问日志是另一条路径，照常留着。
logging.getLogger("httpx").setLevel(logging.WARNING)


# ── 请求 / 响应模型 ──
#
# ★ 为什么要显式写响应模型，而不是 return 那个 dict：
#   pipeline 返回的是【内部结构】（chunks 整个字典都在里面）。
#   直接丢出去等于把内部 schema 变成了接口契约 ——
#   以后改 chunk 的字段名，会静默改掉 API 的形状。
#   显式模型让"接口长什么样"有一处可读的定义。

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    k: int = Field(default=TOP_K, ge=1, le=20)
    expand: bool = Field(default=EXPAND_ENABLED)
    rerank: bool = Field(default=True, description="关掉后走纯 dense，快但 Top-1 会掉")


class Material(BaseModel):
    n: int
    chunk_id: str
    title: str
    section: str
    page_start: int
    score: float
    text: str


class Citation(BaseModel):
    n: int
    quote: str


class AskResponse(BaseModel):
    request_id: str
    question: str
    query: str
    expanded: bool
    k: int
    retriever: str
    status: str
    answer: str | None
    used: list[int]
    citations: list[Citation]
    problems: list[str]
    repairs: list[str]
    note: str | None
    materials: list[Material]
    timings: dict[str, float]
    cached: bool


# ── 进程内唯一的一份装配 ──
#
# ★ 用 lifespan 而不是模块级 Runtime()：模块级会在 import 时就开始加载
#   2GB 的模型 —— 包括 uvicorn --reload 的每一次热重载，以及任何
#   "只是 import 一下看看" 的工具。启动期的活留给启动期。

_runtime: Runtime | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _runtime
    t0 = time.perf_counter()
    logger.info("启动中：加载索引与检索器（首次会加载 cross-encoder 权重）")
    _runtime = Runtime()
    logger.info("就绪：%s 条 chunk，检索器 %s，用时 %.2fs",
                len(_runtime.chunks), _runtime.retriever_names, time.perf_counter() - t0)
    yield
    _runtime = None
    logger.info("已停止")


app = FastAPI(title="Paper RAG Agent", version="0.1.0", lifespan=lifespan)

# 只放行本地前端。★ 不写 allow_origins=["*"]：
# 这个服务会调模型、吃 CPU，公网随便一个页面都能打的 API 不是"方便"，是"没锁"。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _rt() -> Runtime:
    if _runtime is None:      # 理论上只会在启动失败时发生
        raise HTTPException(status_code=503, detail="服务还没就绪")
    return _runtime


@app.get("/api/health")
def health() -> dict:
    return _rt().health()


@app.get("/api/questions")
def questions() -> dict:
    """评测集里的 28 个问题 —— 给界面当「试试这些」用。

    ★ 只回问题文本。queries.json 里还有 targets 和 why（关键事实），
      把它们送进浏览器 = 把答案提前告诉用户，演示就变成抄答案了。
    """
    payload = json.loads((EVAL_DIR / "queries.json").read_text(encoding="utf-8"))
    return {"questions": [item["q"] for item in payload["queries"]]}


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    rt = _rt()
    rid = uuid.uuid4().hex[:8]

    try:
        result = rt.ask(req.question, k=req.k, expand=req.expand,
                        variant="rerank" if req.rerank else "dense")
    except ValueError as e:
        # 参数级错误（比如不认识的检索器名）→ 400，让调用方去改参数，
        # 而不是让它以为"服务坏了"进而重试。
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 —— 外壳要把异常翻成人能读的话
        logger.exception("[%s] 失败：%s", rid, req.question)
        # ★ 500 而不是 200 + 一个空答案：外壳的错和模型的错必须分开。
        #   把"服务炸了"伪装成"模型拒答"，是最难查的一种假绿。
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e

    parsed = result["parsed"]
    resp = AskResponse(
        request_id=rid,
        question=result["question"],
        query=result["query"],
        expanded=result["expanded"],
        k=req.k,
        retriever=result["retriever"],
        status=result["status"],
        answer=(parsed or {}).get("answer"),
        used=(parsed or {}).get("used", []),
        citations=[Citation(n=int(n), quote=q)
                   for n, q in ((parsed or {}).get("quotes") or {}).items()],
        problems=result["problems"],
        repairs=result["repairs"],
        note=result["note"],
        materials=[Material(n=i, chunk_id=r["chunk"]["chunk_id"],
                            title=r["chunk"]["title"], section=r["chunk"]["section"],
                            page_start=r["chunk"]["page_start"],
                            score=round(float(r["score"]), 4),
                            text=r["chunk"]["text"])
                   for i, r in enumerate(result["retrieved"], 1)],
        timings=result["timings"],
        cached=result["cached"],
    )

    # ★ 命中缓存时 timings 是【当初算那次】的数 —— 不许让它看起来像这次花的。
    #   所以缓存分支把话说全：这次花了 0，括号里是"本来要花多久"。
    if result["cached"]:
        logger.info("[%s] %s | %s | 缓存命中（本来要 %.1fs：检索 %.1fs 生成 %.1fs 校验 %.2fs）",
                    rid, result["status"], req.question[:30],
                    result["timings"]["total"], result["timings"]["retrieve"],
                    result["timings"]["generate"], result["timings"]["verify"])
    else:
        logger.info("[%s] %s | %s | 总 %.1fs（检索 %.1fs 生成 %.1fs 校验 %.2fs）",
                    rid, result["status"], req.question[:30],
                    result["timings"]["total"], result["timings"]["retrieve"],
                    result["timings"]["generate"], result["timings"]["verify"])
    return resp
