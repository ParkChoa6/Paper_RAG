"""HTTP 服务层（Stage 8）—— 把 paper_rag 这条线开放给浏览器。

    service/runtime.py   把索引 / 检索器 / 缓存装一次，进程内复用
    service/api.py       FastAPI 路由：只做「收参数 → 调 runtime → 拼 JSON」
    service/ui.py        Streamlit 界面：只做「调 API → 画出来」

★ 这一层的定位：**外壳**。它不含任何业务判断 ——
  检索几条、什么时候拒答、引用算不算通过，全部在 paper_rag/ 里。
  外壳一旦开始做判断，CLI、HTTP、评测就会各自长出一套规则。
"""
