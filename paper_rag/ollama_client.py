"""Ollama 连接 —— 建客户端的那一个地方。

── 它在流水线里的位置 ──

    谁都要调模型，但没人该知道"怎么连"

        embed.py    文本 → 向量   ┐
        llm.py      文本 → 文本   ├──▶ 本模块 make_client() ──▶ Ollama
        其它脚本                  ┘

    它【只依赖 config】，不依赖 embed / llm / pipeline 中的任何一个。
    删掉 embed.py 和 llm.py，它照样能跑 —— 这是它作为"底座"的判据。

── 为什么会多出这个文件（2026-11-19 改主意记录）──

    `llm.py` 末尾原来写着：「两份 make_client 是故意的，等第三处出现再抽」。
    那时它确实只值一行 `ollama.Client(host=...)`，抽出来是为了一行代码
    多加一个模块 —— 不划算。

    后来这行代码长出了【条件】（见下），而且那个条件漏写一次是【看不出来】的：
    生成走不走代理，实测差在噪声里（0.43s vs 0.54s）。也就是说，
    两份里只改一份，另一份会安静地继续绕代理，一年都不会有人发现。

    ★ 这才是该抽的判据：不是"重复了几次"，而是
      「不同步的时候，有没有东西会报错」。
      以前没有 → 可以重复；现在没有 → 不能再重复。
"""

import logging
from urllib.parse import urlparse

import ollama

from paper_rag.config import OLLAMA_HOST

logger = logging.getLogger(__name__)


def make_client() -> ollama.Client:
    """建一个 Ollama 客户端。

    返回:
        ollama.Client，指向 config.OLLAMA_HOST

    ★ 本机地址禁用系统代理（trust_env=False）。

      这台机器上有个系统代理（Windows 注册表，127.0.0.1:7900），
      而 httpx 会把它套到**连 127.0.0.1 的请求**上 —— 也就是说，
      「本地模型」的每一次嵌入和生成都先绕去一个第三方进程。

      【证据，可复现】
          urllib.request.getproxies()
              → {'http': 'http://127.0.0.1:7900', ...}，没有 no_proxy
          httpx.get('http://127.0.0.1:9/x', trust_env=True)
              → HTTP 502        ← 这个 502 是【代理】给的，不是本机给的
          httpx.get('http://127.0.0.1:9/x', trust_env=False)
              → ConnectError    ← 这才是"本机真的没有服务"

      ★ 为什么这么做【不是】为了快 —— 速度差没测出来。
        第一次量的 85ms→15ms 复现不了，重测三遍（各 15~20 次，A/B 交替）：
            走代理  中位 14.1ms · P90 14.9ms · 最大 92.8ms
            直连    中位 13.1ms · P90 14.6ms · 最大 98.9ms
        也就是说：中位数差 ~1ms，尾延迟两次各只有 1 次离群。
        ★ 一条测量只跑一遍就下结论，量到的是"这台机器当时有多忙"。

      ★ 真正的理由是【路径上没有第三方】：
        本机两个进程之间说一句话，不该先经过一个可以被关掉、
        可以被改配置、可以自己吐 502 的进程（上面那个 502 就是它吐的）。
        这是边界问题，不是性能问题。

      ⚠️ 只在【回环地址】上这么做。OLLAMA_HOST 指向远程机器时，
         代理可能正是它能连过去的原因 —— 那种情况下保留 trust_env。
    """
    # 兼容 "http://host:11434" 和手写的 "host:11434" 两种写法：
    # urlparse("localhost:11434") 会把 "localhost" 当成 scheme，hostname 是 None。
    host = (urlparse(OLLAMA_HOST if "//" in OLLAMA_HOST else f"//{OLLAMA_HOST}").hostname or "").lower()
    local = host in ("localhost", "127.0.0.1", "::1")
    return ollama.Client(host=OLLAMA_HOST, trust_env=not local)
