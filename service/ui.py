"""Streamlit 界面 —— 只认 JSON，不 import paper_rag。

── 前后端的分界线 ──

    service/api.py  FastAPI   后端：唯一的业务入口
    service/ui.py   本文件   前端：只做「发请求 → 画结果」

    ★ 这个文件【不 import paper_rag】。它连 chunks.json 在哪都不知道。
      这不是洁癖：只要前端能直接调库，"界面看到的"和"API 给出的"就会
      各走一条路，而分叉的那天不会有任何东西报错。
      （本仓库在 S5-1/S5-2 上各栽过一次同类问题，见 docs/ROADMAP.md 规矩 1）

启动:
    1) 后端：./.venv/Scripts/python.exe -m uvicorn service.api:app --port 8000
    2) 前端：./.venv/Scripts/python.exe -m streamlit run service/ui.py
       （默认开在 http://localhost:8501）

配置:
    PAPER_RAG_API   后端地址，默认 http://127.0.0.1:8000
"""

from __future__ import annotations

import os
import time

import httpx
import streamlit as st

API = os.environ.get("PAPER_RAG_API", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 180.0     # 13 秒是常态，但首次请求要加载重排权重；给足余量

# ★ trust_env=False —— 这台机器上有个系统代理（Windows 注册表里的
#   127.0.0.1:7900），而 httpx 会把它套到【连 127.0.0.1 的请求】上。
#   症状：后端明明活着，界面却报 `502 Bad Gateway` —— 那个 502 是代理给的，
#   不是后端给的。更糟的是，这样一来"本机前后端"之间的每一句话都要
#   经过一个第三方进程。
#   ★ 本机回环不该走代理。这是一条边界，不是优化 ——
#     速度差没测出来（重测三遍，中位 14.1 vs 13.1ms），
#     测出来的是「多一个会自己吐 502 的中间人」。
_client = httpx.Client(trust_env=False)


def api_get(path: str) -> dict:
    try:
        r = _client.get(f"{API}{path}", timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        st.error(f"连不上后端 {API}：{e}\n\n先起 `uvicorn service.api:app --port 8000`。")
        st.stop()


STATUS_TEXT = {
    "answered": ("✅", "已回答", "green"),
    "refused": ("🤷", "拒答（材料里没有答案）", "gray"),
    "suspect": ("⚠️", "可疑：给了答案但没有任何引用", "orange"),
    "parse_failed": ("💥", "解析失败：模型没有按格式交付", "red"),
}


def fmt_seconds(v: float) -> str:
    return f"{v:.1f}s" if v >= 1 else f"{v * 1000:.0f}ms"


def render_answer(res: dict) -> None:
    icon, label, color = STATUS_TEXT.get(res["status"], ("❓", res["status"], "gray"))
    st.markdown(f"### {icon} {label}")
    # ★ 「命中缓存」不在这里说 —— 放在下面耗时那一行说，因为那一行才需要它解释
    #   （否则「总 < 分项之和」看起来像算错了）。同一件事说两遍，读者会以为是两件事。

    if res["status"] == "parse_failed":
        st.error(f"模型输出无法解析：{res['note']}\n\n★ 这不是拒答 —— 是管线没产出。")
        return

    st.markdown(res["answer"] or "（空）")

    if res["status"] == "suspect":
        st.warning(res["note"])
        return

    if res["status"] == "refused":
        st.info(f"材料里没有答案，模型按契约回了「{res['answer']}」。拒答不是错误。")
        return

    # ── 引用 ──
    if res["citations"]:
        st.markdown("**引用原文**")
        for c in res["citations"]:
            st.markdown(f"- `[{c['n']}]` {c['quote']}")

    # ── 校验结果：这是这个项目最该被看见的一屏 ──
    if res["problems"]:
        st.error(f"⚠️ 引用校验发现 {len(res['problems'])} 个问题")
        for p in res["problems"]:
            st.markdown(f"- {p}")
    else:
        st.success("✓ 引用校验通过：每条引文都能在材料原文里找到")

    if res["repairs"]:
        st.warning("✱ 编号修正（按原文反查，不是猜）")
        for r in res["repairs"]:
            st.markdown(f"- {r}")


def render_materials(materials: list[dict]) -> None:
    st.markdown("**检索到的材料**")
    for m in materials:
        used = "★ " if m["n"] in st.session_state.get("used", []) else ""
        with st.expander(f"{used}[{m['n']}] {m['title']} · {m['section']} · 第 {m['page_start']} 页 · 分数 {m['score']:+.4f}"):
            st.text(m["text"])


def render_result(res: dict, elapsed: float) -> None:
    """把一条结果画完：判定 → 正文 → 引用 → 校验 → 耗时 → 材料。

    ★ 单独拆出来不是为了好看：Streamlit 每次交互都会【从头重跑整个脚本】。
      不把"上次的结果"放进 session_state 再重画一遍，用户调一下 k 滑块，
      答案就会从屏幕上消失 —— 而看起来像"系统崩了"。
    """
    render_answer(res)
    t = res["timings"]
    parts = (f"检索 {fmt_seconds(t['retrieve'])} · 生成 {fmt_seconds(t['generate'])}"
             f" · 校验 {fmt_seconds(t['verify'])}")
    tail = f" · 检索器 `{res['retriever']}` · k={res['k']}"
    if res["cached"]:
        # ★ 命中缓存时【不能】写「总 X 秒（检索 a · 生成 b · 校验 c）」——
        #   这次确实只花了 X，但那三个数是【当初算那次】的，加起来比 X 大。
        #   「总 < 分项之和」这种数一旦出现在界面上，就没人会再相信这一行。
        st.caption(f"这次 {fmt_seconds(elapsed)} —— 命中缓存，没有重算；"
                   f"原本要 {fmt_seconds(t['total'])}（{parts}）{tail}")
    else:
        st.caption(f"总 {fmt_seconds(elapsed)}（{parts}）{tail}")
    if res["expanded"]:
        st.caption(f"检索用的文本（已扩展）：{res['query']}")
    st.divider()
    render_materials(res["materials"])


def main() -> None:
    st.set_page_config(page_title="Paper RAG Agent", page_icon="📄", layout="wide")

    health = api_get("/api/health")

    with st.sidebar:
        st.header("系统状态")
        st.write(f"语料 **{health['chunks']}** 条 · 维度 {health['dim']}")
        st.write(f"嵌入 `{health['emb_model']}`")
        for variant, name in health["retrievers"].items():
            st.caption(f"{variant}: {name}")
        st.divider()
        st.write(f"启动耗时 {health['load_seconds']}s · 已运行 {fmt_seconds(health['uptime_seconds'])}")
        st.write(f"问答 {health['n_asks']} 次 · 缓存命中 {health['n_cache_hits']} 次")
        if health.get("n_failures"):
            st.write(f"⚠️ 失败 {health['n_failures']} 次")
        st.divider()
        rerank = st.toggle("cross-encoder 重排", value=True,
                           help="关掉后快约 10 倍，但 Top-1 从 68% 掉到 50%")
        k = st.slider("检索条数 k", 1, 10, 5)
        st.caption("⚠️ 同一句话 1 小时内走缓存；改 k 或重排开关会重新计算。")

    st.title("📄 Paper RAG Agent")
    st.caption("7 篇知识图谱论文 · 1345 段 · 全手写检索 → 生成 → 逐条核对引用")

    st.session_state.setdefault("answer", None)
    st.session_state.setdefault("elapsed", 0.0)

    suggestions = api_get("/api/questions")["questions"]
    typed = st.text_area("问一句话", height=80,
                         placeholder="例：KGE 模型是按什么标准分类的？")
    cols = st.columns([1, 3])
    with cols[0]:
        ask_clicked = st.button("提问", type="primary", use_container_width=True)
    with cols[1]:
        picked = st.selectbox("或者从评测集里挑一个", ["—"] + suggestions, index=0)

    # 输入框优先；空着就用下拉里选的那个。两条路都通到同一个变量，
    # 免得"忘了把 selectbox 的值写回 q"这种 bug。
    question = typed.strip() or (picked if picked != "—" else "")

    if ask_clicked:
        if not question:
            st.warning("先输入一个问题，或者从评测集里挑一个。")
        else:
            stage = st.empty()
            t0 = time.perf_counter()
            stage.info(f"① 检索 + 重排 → ② 生成 → ③ 核对引用 … 预计 "
                       f"{'3' if not rerank else '13'} 秒")
            try:
                with st.spinner("正在检索并生成…"):
                    r = _client.post(f"{API}/api/ask",
                                     json={"question": question, "k": k, "rerank": rerank},
                                     timeout=TIMEOUT)
            except httpx.HTTPError as e:
                stage.empty()
                st.error(f"请求失败：{e}")
                r = None
            elapsed = time.perf_counter() - t0

            if r is not None:
                stage.empty()
                if r.status_code != 200:
                    st.error(f"后端返回 {r.status_code}：{r.text}")
                else:
                    res = r.json()
                    st.session_state.answer = res
                    st.session_state.elapsed = elapsed
                    st.session_state.used = res.get("used", [])

    # ── 画「当前这条」──
    # 无论是刚问完，还是用户调了滑块导致脚本重跑，走的都是这一段。
    res = st.session_state.answer
    if res:
        st.caption(f"问：**{res['question']}**")
        render_result(res, st.session_state.elapsed)


main()
