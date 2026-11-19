"""界面探针 —— 不靠人眼，把前端按一遍。

── 它在三层里的位置 ──

    paper_rag/   产品   检索 → 生成 → 校验（不 import 本文件的任何东西）
    service/     外壳   api.py（后端） + ui.py（前端）
  ★ scripts/     脚手架 本文件：只做「按按钮 → 断言屏幕上出现了什么」

    它【不属于服务】。删掉它，服务照常跑；它坏了，服务也没坏。
    它是"仪器"：把「界面看起来对」变成「这 19 条断言全过」。

── 为什么用 AppTest 而不是开浏览器点 ──

    Streamlit 有官方的 streamlit.testing.v1.AppTest：
    它在【同一个 Python 进程里】把 ui.py 当脚本跑一遍，
    然后把 st.title / st.markdown / st.caption / st.button 全部变成可读对象。

    人眼点一遍能发现的：界面崩了、答案没出来。
    人眼点【看不出来】的：缓存那一行的数字加起来不等于总数、
                       拖一下滑块答案就消失、改 k 之后拿到的是旧结果。
    ★ 这一层专门量后者。

── 怎么跑 ──

    1) 先把后端起起来：
         ./.venv/Scripts/python.exe -m uvicorn service.api:app --port 8000
    2) 再跑本探针：
         PYTHONIOENCODING=utf-8 PYTHONPATH=. ./.venv/Scripts/python.exe scripts/probe_ui.py

    退出码 0 = 全过；1 = 有没过关的（会把是哪一条打出来）。

── 一个坑（写在这里，免得下次又踩）──

    缓存是【服务进程级】的，跑第二遍时第一遍的问题还在里面。
    所以「改 k 会重算」这一关不能用 k=7 —— 那测的是"缓存对不对"。
    改成用一个没问过的 k，并且断言 *材料条数* 跟着 k 变
    （条数对不上，才是真的拿了旧结果顶）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "service" / "ui.py"
API = os.environ.get("PAPER_RAG_API", "http://127.0.0.1:8000").rstrip("/")

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(("✅ " if cond else "❌ ") + name + (f"   {detail}" if detail else ""))


def fresh():
    from streamlit.testing.v1 import AppTest
    # 180s：重排那次真的会跑十几秒；给足余量，别让"慢"伪装成"挂"
    return AppTest.from_file(str(UI), default_timeout=180.0)


def backend_up() -> bool:
    import httpx
    try:
        httpx.get(f"{API}/api/health", trust_env=False, timeout=5).raise_for_status()
        return True
    except Exception:
        return False


def main() -> int:
    if not backend_up():
        print(f"❌ 后端没起来（{API}）—— 先跑：\n"
              f"   ./.venv/Scripts/python.exe -m uvicorn service.api:app --port 8000")
        return 1

    # ── 关 1：首屏 ─────────────────────────────────────────────────
    at = fresh()
    at.run()
    check("首屏无异常", not at.exception,
          "; ".join(str(e.value) for e in at.exception)[:120])
    check("标题在", any("Paper RAG" in str(t.value) for t in at.title))
    sb = " ".join(str(m.value) for m in at.sidebar.markdown)
    check("侧栏读到了语料条数", "1345" in sb, sb[:50])
    check("还没提问时不显示结果",
          not any("问：" in str(c.value) for c in at.caption))

    # ── 关 2：提问 → answered 路径 ────────────────────────────────
    at.text_area[0].set_value("KGE 模型是按什么标准分类的？").run()
    at.button[0].click().run()
    body = " ".join(str(m.value) for m in at.markdown)
    ok_msg = " ".join(str(m.value) for m in at.success)
    err_msg = " ".join(str(m.value) for m in at.error)
    # ★ 四种判定都算"画对了" —— 这一关查的是【有没有给出判定】，
    #   不是"模型答得对不对"。后者是 eval_answer.py 的事。
    check("给出了判定标签",
          any(w in body for w in ("已回答", "拒答", "可疑", "解析失败")), body[:60])
    check("引用校验有一句结论",
          ("引用校验通过" in ok_msg) or ("引用校验发现" in err_msg),
          f"success={ok_msg[:30]!r}")
    check("耗时那一行在",
          any("检索" in str(c.value) and "生成" in str(c.value) for c in at.caption))
    first = at.session_state["answer"]
    print(f"     → status={first['status']} k={first['k']} cached={first['cached']}")

    # ── 关 3：同一句再问 → 缓存文案必须换一套说法 ────────────────
    at.button[0].click().run()
    caps = [str(c.value) for c in at.caption]
    hit = [c for c in caps if "命中缓存" in c]
    check("第二次命中缓存", bool(hit), hit[0][:70] if hit else "没找到缓存文案")
    # ★ 这条是 S8-2 真踩过的 bug：缓存命中时如果照抄
    #   「总 X（检索 a · 生成 b · 校验 c）」，a+b+c 会比 X 大得多
    #   （那些分项是【当初算那一次】的数）。「总 < 分项之和」一出现，
    #   这一行就再没人信了。
    check("缓存时不写「总 X（检索a·生成b）」",
          not [c for c in caps if c.startswith("总 ")])
    check("缓存时仍说清「原本要多久」", any("原本要" in c for c in hit))

    # ── 关 4：拖滑块 → 结果不能消失 ──────────────────────────────
    q_before = at.session_state["answer"]["question"]
    at.slider[0].set_value(7).run()
    check("拖滑块后结果还在", at.session_state["answer"] is not None)
    caps4 = " ".join(str(c.value) for c in at.caption)
    body4 = " ".join(str(m.value) for m in at.markdown)
    check("拖滑块后屏幕上还看得到答案", q_before in caps4 or q_before in body4)
    k_cap = [c for c in (str(x.value) for x in at.caption) if "k=" in c]
    # ★ 屏幕上现在是【旧 k】的结果。让它自己说出是按哪个 k 算的，
    #   比"用户自己记得原来拖到几"可靠。
    check("耗时行说出了它是按 k=几 算的", any("k=5" in c for c in k_cap), str(k_cap)[:60])

    # ── 关 5：换一个没用过的 k → 材料条数必须跟着变 ──────────────
    at.slider[0].set_value(9).run()
    at.button[0].click().run()
    r5 = at.session_state["answer"]
    print(f"     → k={r5['k']} cached={r5['cached']} 材料 {len(r5['materials'])} 条")
    check("返回的 k 是 9", r5["k"] == 9)
    check("材料条数跟着 k=9 变（没拿旧缓存顶）",
          len(r5["materials"]) == 9, f"{len(r5['materials'])} 条")

    # ── 关 6：关掉重排 → 更快，且检索器名字变了 ──────────────────
    at.toggle[0].set_value(False).run()
    at.button[0].click().run()
    r6 = at.session_state["answer"]
    print(f"     → retriever={r6['retriever']} 总 {r6['timings']['total']:.1f}s")
    check("检索器切到 dense", r6["retriever"].startswith("dense:"))
    check("关重排确实快",
          r6["timings"]["total"] < r5["timings"]["total"],
          f"{r6['timings']['total']:.1f}s vs {r5['timings']['total']:.1f}s")

    # ── 关 7：后端不通 → 报错，不是画一个空答案 ─────────────────
    os.environ["PAPER_RAG_API"] = "http://127.0.0.1:9"
    try:
        at2 = fresh()
        at2.run()
        errs = [str(e.value) for e in at2.error]
        check("后端不通时给 error 而不是空答案",
              any("连不上后端" in e for e in errs), str(errs)[:80])
        check("报错里写了该敲什么命令", any("uvicorn" in e for e in errs))
    finally:
        os.environ.pop("PAPER_RAG_API", None)

    passed = sum(1 for _, c, _ in RESULTS if c)
    print(f"\n{passed}/{len(RESULTS)} 通过")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
