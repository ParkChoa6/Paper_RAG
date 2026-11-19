"""文本生成 —— 文本 → 文本。

和 embed.py 是兄弟，但方向相反：

    embed.py   文本 → 向量    为了【找得到】
    llm.py     文本 → 文本    为了【答得出】

两个都是「薄薄一层 Ollama 封装」—— 不知道 chunk 是什么，
不知道 prompt 该怎么拼，不知道什么叫"引用"。

为什么单独拆成模块（0B-2 判据二）：
    它【被所有人依赖，但它谁都不依赖】。
    generator.py 依赖它，Stage 6 的 Agent 也会依赖它，
    而它只依赖 config 和 ollama。
    业务知识一旦长进这一层，Stage 6 就没法复用它了。
"""

import logging

# ★ make_client 已经搬到 paper_rag/ollama_client.py（2026-11-19）。
#   这里【再导出】一次是故意的，让 `from paper_rag.llm import make_client`
#   的老脚本原样能用。理由和来龙去脉见文件末尾。
#
#   （`import ollama` 和 `OLLAMA_HOST` 随之不再需要：这个文件只管
#     "怎么生成"，不管"怎么连"。）
from paper_rag.ollama_client import make_client  # noqa: F401  re-export

logger = logging.getLogger(__name__)


def generate(
    client,
    model: str,
    prompt: str,
    options: dict | None = None,
    format=None,
) -> str:
    """单轮生成：给一段 prompt，拿一段文本回来。

    参数:
        client:   ollama 客户端
        model:    模型名（config.GEN_MODEL）
        prompt:   完整的 prompt 字符串
        options:  透传给 Ollama 的生成参数，比如
                    {"temperature": 0, "num_predict": 512, "seed": 42}
        format:   ★ S5-7：透传给 Ollama 的 `format` —— 【约束解码】。
                  传一个 JSON Schema（dict）或 "json"（裸语法），
                  采样器就被限死在合法输出上；传 None = 不约束。
                  ⚠️ 参数名就叫 format（和 Ollama 的关键字【同名】），
                     这是故意的：想找"哪次调用约束了解码"，grep format 就够。
                     代价是它在本函数里遮住了内置 format() —— 本函数不用那个。
                  ⚠️ 别传裸 "json"：实测会触发 Ollama 的重复保护直接 500。
                     理由见 config.GEN_JSON_SCHEMA 的注释。

    返回:
        str —— 模型输出的【原文】

    注意:
        这一层不做任何解析、不做任何校验。模型说什么就原样返回什么。
        【判断是上层的事。】
        这一层多写一行"帮它清理一下输出"，你就再也说不清
        到底是模型没按格式答，还是你替它圆过去了。

        ★ format 不违反这条：它不是"替它清理输出"，
          它是【在模型开口之前就限死它的嘴】——
          走过来说的话依然是模型自己说的，一个字没被改。
    """
    resp = client.generate(model=model, prompt=prompt, options=options or {},
                           format=format)
    return resp.response


# ---------------------------------------------------------------------------
# 关于 make_client：曾经有两份拷贝，2026-11-19 抽掉了
#
# 【当时的决定】embed.py 和 llm.py 各写一份 `ollama.Client(host=...)`。
#   理由：只有一行，抽到独立模块是"为一行代码多一个文件"；
#        抽到 embed.py 又会让 llm 假依赖 embed。
#        结论是先重复，等第三处出现再抽。
#
# 【现在改了】不是因为第三处出现了，而是因为那行代码长出了【条件】：
#   OLLAMA_HOST 是本机时必须 trust_env=False（本机两个进程之间不该先经过
#   系统代理那个第三方进程），是远程时必须 trust_env=True（代理可能正是它连得过去的原因）。
#
#   判据换了：
#     旧判据 —— 「重复了几次」
#     新判据 —— 「两份不同步的时候，有没有东西会报错」
#
#   旧的一行：不同步只是写法丑，行为一样。可以等。
#   新的带条件的逻辑：不同步 = 一份绕代理、一份不绕。
#     ★ 而且这个不同步是【静默】的 —— 实测两条路的耗时差不多
#       （中位 14.1ms vs 13.1ms，重测三遍都在这附近），
#       所以少写一份不会慢到让人察觉，只会悄悄多一个会吐 502 的中间人。
#     ★ 这才是"重复到该抽"的真正信号：不是长度，是【出错时不会喊】。
#
# 现在 :paper_rag/ollama_client.py 一处定义，两个模块各自 re-export。
# 十几个脚本里的 `from paper_rag.embed import make_client` 一个字没改。
# ---------------------------------------------------------------------------
