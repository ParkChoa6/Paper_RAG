# 实例演示

> **这份文件里没有一处是"格式示意"。** 每段输出都是 2026-11-19 在本机
> 真跑出来的逐字记录，命令一起贴在每节开头，可以照着复现。
>
> 数字（分数、秒数）每次跑都会变，文字也会随题变化 —— 但**结构**不会：
> 哪一行是检索器说的、哪一行是模型说的、哪一行是代码核对的，位置永远固定。

---

## 目录

- [0. 运行环境](#0-运行环境)
- [1. 演示一：一句能答的](#1-演示一一句能答的)
- [2. 演示二：查询扩展长什么样](#2-演示二查询扩展长什么样)
- [3. 演示三：材料里没有 → 拒答](#3-演示三材料里没有--拒答)
- [4. 演示四：★ 引用是真的，答案仍然是错的](#4-演示四-引用是真的答案仍然是错的)
- [5. 演示五：服务层（HTTP）](#5-演示五服务层http)
- [6. 演示六：引用校验能抓什么、抓不到什么](#6-演示六引用校验能抓什么抓不到什么)
- [7. 复现清单](#7-复现清单)
- [8. 这六段演示证明了什么、没证明什么](#8-这六段演示证明了什么没证明什么)

---

## 0. 运行环境

| 项 | 值 |
|---|---|
| 时间 | 2026-11-19 14:43 – 15:00 |
| Python | 3.13.9（`.venv`） |
| Ollama | 本机，模型 `qwen2:7b` / `bge-m3:latest` |
| 语料 | 1345 条 chunk / 7 篇论文 |
| 索引 | `(1345, 1024) float32` |
| 重排 | `bge-reranker-v2-m3`，CPU |
| 生产检索器 | `dense:bge-m3:latest:raw > ce:bge-reranker-v2-m3:cpu @pool50` |

> 时间一律是**这次机器上**的数。第一次用到重排时要加载约 568MB 权重，
> 那一题的检索会到 25 秒；权重进内存之后是 12 ~ 15 秒。
> 看到"检索 25s"不要以为是坏了，看它是不是进程里第一次。

---

## 1. 演示一：一句能答的

```powershell
python scripts/ask.py "RotatE 把关系建模成什么操作？"
```

```
语料 1345 条 · 索引 (1345, 1024) · 嵌入 bge-m3:latest · 生成 qwen2:7b
查询扩展: 开   k=5
检索器: dense:bge-m3:latest:raw > ce:bge-reranker-v2-m3:cpu @pool50
==============================================================================
问: RotatE 把关系建模成什么操作？

--- 检索到 5 条 ---
    检索器: dense:bge-m3:latest:raw > ce:bge-reranker-v2-m3:cpu @pool50
  [1] +0.9629  Knowledge Graph Embedding: An Overview  (2.1 Distance-based Models，第 12 页)
      RotatE [94] models entities in the complex vector space and interprets relations
  [2] +0.9276  A Survey of Knowledge Graph Reasoning on Graph Types: Static, Dynamic, and Multi-Modal  (A. Review on Reasoning Techniques，第 5 页)
      Meanwhile, some translational models try to find different hyperplanes to achiev
  [3] +0.8773  Overview of knowledge reasoning for knowledge graph  (3.2. Triplet reasoning based on embedding，第 4 页)
      In addition to the optimization embedding methods mentioned above, scholars have
  [4] +0.8248  Knowledge Graph Embedding: An Overview  (2.1 Distance-based Models，第 12 页)
      This modification leads to better modeling capability of hierarchy structures in
  [5] +0.7907  Knowledge Graph Embedding: An Overview  (2.4 Connections between KGE Models，第 18 页)
      Quite a few models also leverage scaling operation that is first demonstrated by
    （分数只在本次输出内部可比，用于排序；跨检索器不可比）

--- 结果 [OK  ] ---
  RotatE 把关系建模成旋转操作。

  引用了: [1]
    [1] RotatE [94] models entities in the complex vector space and interprets relations as rotati

  ✓ 引用校验通过（每条 quotes 都能在材料原文里找到）
```

**这段输出里三件事必须分开读**：

| 谁说的 | 是哪几行 | 可信度 |
|---|---|---|
| 检索器 | `+0.9629`、标题、章节、页码 | 分数**只在本次输出内部**可比 |
| 模型 | `RotatE 把关系建模成旋转操作。` | 结论，可能错 |
| 代码 | `✓ 引用校验通过` | 只保证**那条原句**在材料里逐字存在 |

★ 注意答案只有一句话。这不是保守 —— 模型的回答在这套契约下就是"照材料说"，
而 [1] 这句材料本身就是一句话把事说完的。**答案短不是缺陷，是材料短的直接后果。**

---

## 2. 演示二：查询扩展长什么样

同一个命令，第二题（中文问、英文语料，靠扩展表接上）：

```powershell
python scripts/ask.py "知识图谱嵌入模型是按什么标准分类的？"
```

```
问: 知识图谱嵌入模型是按什么标准分类的？
检索用的文本: 知识图谱嵌入模型是按什么标准分类的？ KGE knowledge graph embedding

--- 检索到 5 条 ---
    检索器: dense:bge-m3:latest:raw > ce:bge-reranker-v2-m3:cpu @pool50
  [1] +0.9476  Knowledge Graph Embedding: An Overview  (2 Existing Models，第 8 页)
      KGE models are often categorized based on scoring functions and tools applied to
  [2] +0.8148  A Survey of Knowledge Graph Reasoning on Graph Types: Static, Dynamic, and Multi-Modal  (A. Review on Reasoning Techniques，第 4 页)
      Static KGR models can be categorized into embedding-based, path-based, and rule-
  [3] +0.7557  Multi-hop reasoning of knowledge chain over fuzzy spatiotemporal knowledge graphs with box embeddings  (1. Introduction，第 2 页)
      In the era of data explosion, we face challenges in dealing with massive data. K
  [4] +0.7301  Multi-hop reasoning of knowledge chain over fuzzy spatiotemporal knowledge graphs with box embeddings  (2. Related work，第 3 页)
      Knowledge Graph Model Knowledge Embedding Method Types
  [5] +0.7222  Multi-hop reasoning of knowledge chain over fuzzy spatiotemporal knowledge graphs with box embeddings  (2. Related work，第 3 页)
      For uncertain knowledge graph embeddings. For uncertain knowl­ edge graph embedd

--- 结果 [OK  ] ---
  知识图谱嵌入模型通常根据评分函数和用于建模实体-关系交互和表示的工具来分类。主要分为两类：1）基于距离的模型，2）语义匹配模型。

  引用了: [1]
    [1] KGE models are often categorized based on scoring functions and tools applied to model ent

  ✓ 引用校验通过（每条 quotes 都能在材料原文里找到）
```

★ 关键是那行 `检索用的文本:` —— **扩出来的英文只喂给检索器，prompt 里的问题还是原话。**
不印这一行的话，「中文问题也能搜到英文材料」这件事看起来像变魔术。

★ 也顺手能看出边界：第 [2] 条讲的是 **KGR**（推理）的三分类，不是 **KGE**（嵌入）的
两分类 —— 长得像，但不是答案。重排把它压到第 2 位没压下去，最后靠模型读对了 [1]。
这类"近义干扰"是这套语料最容易翻车的地方。

---

## 3. 演示三：材料里没有 → 拒答

```powershell
python scripts/ask.py --no-rerank --quiet "红烧肉怎么做比较好吃？"
```

```
语料 1345 条 · 索引 (1345, 1024) · 嵌入 bge-m3:latest · 生成 qwen2:7b
查询扩展: 开   k=5
检索器: dense:bge-m3:latest:raw
==============================================================================
问: 红烧肉怎么做比较好吃？

--- 结果 [拒答] ---
  资料未提及

  （材料里没有答案，模型按契约拒答了）
```

★ 拒答是**契约的一部分**，不是失败：prompt 里写死了"材料里没有就输出这个"。
所以它在整条链路上和"答对了"一样，都是 `status = answered/refused` 里合法的一档，
不是异常、不该重试。

⚠️ 但下一节会让这件事变得不那么简单。

---

## 4. 演示四：★ 引用是真的，答案仍然是错的

这一节是**故意**的：问一个**话题相近、但语料里没有答案**的问题。

```powershell
python scripts/ask.py --no-rerank "BERT 的预训练目标是什么？"
```

```
--- 检索到 5 条 ---
    检索器: dense:bge-m3:latest:raw
  [1] +0.5264  Knowledge Graph Embedding: An Overview  (5.2 Pretrained Language Models for Knowledge Graph Completion，第 37 页)
      hibit comparable performance as that from BERT. BERTRL [138] fine-tunes PLM by u
  [2] +0.5206  Knowledge Graph Embedding: An Overview  (5.2 Pretrained Language Models for Knowledge Graph Completion，第 36 页)
      these descriptions. PLMs are transformer-based models with many model parameters
  [3] +0.4570  Overview of knowledge reasoning for knowledge graph  (6.4. Multilingual commonsense reasoning，第 19 页)
      Devlin et al. [159] trained BERT using a multilingual database. Conneau and Lamp
  [4] +0.4554  Multi-hop interpretable meta learning for few-shot temporal knowledge graph completion  (1 ri : ti denotes path embedding for the relation and timestamps chain r1 : t1→r2 : t2→⋯rn : tn，第 7 页)
      Specific meta-learning training process of FTMI model is shown in Algorithm 1. S
  [5] +0.4524  Multi-hop interpretable meta learning for few-shot temporal knowledge graph completion  (3.4. Meta-learning training process，第 7 页)
      In this section, the meta-learning method to train the FTMI model and enable it

--- 结果 [OK  ] ---
  BERT 的预训练目标是下一个句子预测任务。

  引用了: [2]
    [2] BERT is a pretrained bidirectional language model that is built based on transformer archi

  ✓ 引用校验通过（每条 quotes 都能在材料原文里找到）
```

**这段是错的，而且校验器抓不到它。** 三件事同时成立：

1. 检索分数从 0.96 掉到 **0.52** —— 检索层其实"知道"没有好材料，但它没有说出口。
2. 模型没有拒答，它答了，而且答得不全对（BERT 的预训练目标有 **MLM + NSP 两个**，
   这里只说了一个）。
3. `[2]` 那句原文**逐字存在**，但它讲的是"PLM 是 transformer 架构" —— **根本没提 NSP**。
   引用是真的，结论是借来的。

> **这一层查得出「无中生有」，查不出「有中生错」。**
> 引用校验问的是"这句话材料里有没有"，不是"这句话支不支持这个结论"。
> 后者需要读懂论文 —— 那是在写一个笨拙的 BERT，不在这一层的职责里。

`scripts/probe_cite.py` 把这件事完整地演示了一遍（不是构造的，是真跑的）：

```
★ 校验【全部放行】。而答案是错的。
   这不是 bug：这一层查的是引用真不真，不是答案对不对。
   「引用逐字为真 + 结论错误」在它的判据里【结构上就看不见】。
```

**为什么要把这段放进演示文档**：因为一个只放成功案例的演示，会让你
误以为 `✓ 引用校验通过` 等于"答案可信"。**它不等于。** 它等于"引文没有伪造"。

---

## 5. 演示五：服务层（HTTP）

两个终端，先起后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn service.api:app --port 8000
```

### 5.1 健康检查

```
GET /api/health
```

```json
{
  "ok": true,
  "chunks": 1345,
  "dim": 1024,
  "emb_model": "bge-m3:latest",
  "retrievers": {
    "rerank": "dense:bge-m3:latest:raw > ce:bge-reranker-v2-m3:cpu @pool50",
    "dense": "dense:bge-m3:latest:raw"
  },
  "load_seconds": 0.15,
  "uptime_seconds": 6.8,
  "n_asks": 0,
  "n_cache_hits": 0,
  "n_failures": 0
}
```

★ 两个检索器**启动时就建好**，所以 `/health` 能如实报出名字 ——
而不是等第一个请求来了才发现检索器根本建不出来。
★ `load_seconds = 0.15` 说明**重排权重没在这一步加载**（懒加载），
所以"后端 0.15 秒起来了"不等于"第一个问题会很快"。

### 5.2 一次问答

```
POST /api/ask    {"question": "USTKGE 提出了哪两类逻辑约束？", "k": 5, "rerank": true}
```

```json
{
  "request_id": "074f0153",
  "question": "USTKGE 提出了哪两类逻辑约束？",
  "query": "USTKGE 提出了哪两类逻辑约束？ …",
  "expanded": true,
  "k": 5,
  "retriever": "dense:bge-m3:latest:raw > ce:bge-reranker-v2-m3:cpu @pool50",
  "status": "answered",
  "answer": "USTKGE 提出了两类逻辑约束，即传递性约束（transitive constraint）和时空约束（spatiotemporal constraint）",
  "used": [1, 2],
  "citations": [
    {"n": 1, "quote": "In Section 4.2, we proposed two kinds of logic constraints of USTKGE."},
    {"n": 2, "quote": "We identify two logical constraints for USTKGE, namely, the transi­ tivity constraint and the spatiotemporal constraint."}
  ],
  "problems": [],
  "repairs": [],
  "note": null,
  "materials": [ … 5 条，字段 n / chunk_id / title / section / page_start / score / text … ],
  "timings": {"expand": 0.0, "retrieve": 15.32, "generate": 3.582, "verify": 0.0, "total": 18.902},
  "cached": false
}
```
（`materials` 在这里省略；`query` 和 `citations[].quote` 是原样，没有截断。）

★ **接口里的 `status` / `problems` / `repairs` 和 CLI 是同一个来源** ——
`service/` 不判任何一个，只转述 `pipeline.ask()`。所以两边不会分叉。

### 5.3 同一句话再问一次（缓存）

```
POST /api/ask    （同一句，同一个 k / rerank）
→ 墙钟 0.0185s   cached: true   timings.total: 15.793
```

```json
{ "ok": true, "chunks": 1345, "n_asks": 2, "n_cache_hits": 2, "n_failures": 0 }
```

⚠️ `timings` 命中的是**当初算那次**的数。所以 `cached: true` 时
不能把 `total` 读成"这次花了 15.8 秒" —— 这次花了 18 毫秒。
界面那边专门为这个写了一行：`这次 2ms —— 命中缓存，没有重算；原本要 16.0s`。

### 5.4 界面的 19 条断言（不开浏览器也能验）

```powershell
python scripts/probe_ui.py
```

```
✅ 首屏无异常
✅ 标题在
✅ 侧栏读到了语料条数   语料 **1345** 条 · 维度 1024 嵌入 `bge-m3:latest` 启动耗时 0.
✅ 还没提问时不显示结果
✅ 给出了判定标签   ### ✅ 已回答 …
✅ 引用校验有一句结论   success='✓ 引用校验通过：每条引文都能在材料原文里找到'
✅ 第二次命中缓存   这次 2ms —— 命中缓存，没有重算；原本要 16.0s（检索 12.6s · 生成 3.4s · 校验 0ms）
✅ 材料条数跟着 k=9 变（没拿旧缓存顶）   9 条
✅ 检索器切到 dense
✅ 关重排确实快   0.9s vs 13.9s
✅ 后端不通时给 error 而不是空答案   ['连不上后端 http://127.0.0.1:9：[WinError 10061] …']
✅ 报错里写了该敲什么命令

19/19 通过
```

（上面是 19 条里的几行，完整列表跑一遍就有。）

> Streamlit 界面本身：
> `.\.venv\Scripts\python.exe -m streamlit run service/ui.py` → <http://localhost:8501>

---

## 6. 演示六：引用校验能抓什么、抓不到什么

```powershell
python scripts/probe_cite.py
```

三块内容：**离线构造输入**（不调模型）、**诱导伪造**（调模型）、**已知抓不住的**。

### 6.1 离线：9 条引用病 + 8 条修正规则

```
✅ 全部对得上                  报出 0 条   两条引用逐字来自材料
✅ 真·拒答                    报出 0 条   两边都空 —— 拒答不是错误，别报出来
✅ 编号越界                    报出 1 条   引用了不存在的第 9 条材料
     └─ 引用 [9] 越界：当前只有 3 条材料
✅ 说了用、交不出原句           报出 1 条   声称用了 2，却没有 2 的原句
     └─ 引用 [2]：声称使用但未提供原文
✅ 交了原句、没说过要用         报出 1 条   给了 3 的原句，却不承认用了 3
     └─ 引用 [3]：提供了原文但未声明使用
✅ ★ 伪造引用                  报出 1 条   这句话材料里根本没有 —— 这一关是本层存在的理由
     └─ 引用 [1]：原文中找不到对应内容（疑似伪造）
✅ ★ 一真一假                  报出 1 条   第二条是伪造的 —— 只看第一条的实现会漏掉它
     └─ 引用 [3]：原文中找不到对应内容（疑似伪造）
✅ ★ 键带前导空格              报出 0 条   键写成 ' 1' —— 编号没错、原句也真，不该报任何问题
✅ ★ 重复编号只报一次          报出 1 条   9 越界，但【越界】这件事只有一件 —— 报两遍是 bug

  9/9 通过（观察项不计分）
```

```
✅ 全部对得上         没事可修的时候不许乱改
✅ ★ 单条错配         原句来自材料 3，编号和正文一起改
✅ ★ 两条互换         同时替换，不能先改一个再改另一个
✅ 真伪造不动         哪儿都找不到 = 编造，不是编号问题
✅ 原句两处都有 → 不动    归属不唯一时宁可不修，交给 verify 报
✅ 纠正后撞车 → 整批不动  两条引用指到同一份材料，说明至少一条判错了
✅ 拒答不动           没有编号可言
✅ 正文里的 [94] 不动  只改【被纠正过的】编号；论文里的 [94] 不是材料编号

  8/8 通过
```

★ 前 4 条 `★` 是**每一轮都可能是新病**：它们不是从"要报错"推出来的，
是从"报错文案是压缩过的"这件事反推出来的 —— 同一个"引用有问题"背后有 4 种病。

### 6.2 诱导：把拒答规则拿掉，看模型编不编

```
手法：把 build_prompt 的拒答规则【拿掉】，改成「quotes 不许为空」。
每题都是「模型知道答案、库里查不到」。2 题 × 4 seed = 8 次。
★ 编不编【不保证复现】，所以看比例，不看单次：
  跑一次没编 ≈ 抛硬币抛到反面，据此说『模型不编』是错的结论。
```

本次运行的结果：

```
★ 诱导有效：5/8 次真的编了，verify 每次都抓住。
```

其中一次（seed = 1）：

```
问题：Attention Is All You Need 这篇论文的作者是谁？   （Transformer 作者，全库 0 命中）

{"answer": "Attention Is All You Need 这篇论文的作者是 Vaswani, Shazeer, Parmar, Uszkoreit, Jones, Gomez, Kaiser, and Polosukhin。", "used": [1], "quotes": {"1": "A graph attention mechanism with neural modules"}}

used = [1]
  quotes[1] ✅ ①在 ②在 ③在   逐字就在正文里
verify 报出 0 条：
  ○ 这一次模型【没编引用】—— 探针三层判据也只数出 0 条伪造。
```

★ 注意这次是**没编**的那一半：它答对了作者（模型脑子里就知道），
并且从材料里翻了一句**真**的图注意力原句贴上来。这次的问题是"引文不支撑结论"，
不是"引文是假的" —— **和 §4 同一个病**。
所以这 8 次的正确读法是：**5/8 编了假引文（被抓住），另外 3/8 是"真引文、错关联"（抓不住）。**

---

## 7. 复现清单

```powershell
# 0) 前置
ollama serve
python check_env.py

# 1) 单句问答
python scripts/ask.py "RotatE 把关系建模成什么操作？"

# 2) 连问几句
python scripts/ask.py "知识图谱嵌入模型是按什么标准分类的？" "多模态知识图谱分为哪两种？"

# 3) 关掉重排（快约 10 倍，Top-1 从 68% 掉到 50%）
python scripts/ask.py --no-rerank "红烧肉怎么做比较好吃？"

# 4) 起服务
python -m uvicorn service.api:app --port 8000
curl http://127.0.0.1:8000/api/health

# 5) 验界面（先起后端）
python scripts/probe_ui.py

# 6) 验引用校验
python scripts/probe_cite.py

# 7) 端到端三个 arm（28 题，约 10 分钟）
python scripts/eval_answer.py
```

---

## 8. 这六段演示证明了什么、没证明什么

**证明了**

- 一条完整的链路是通电的：中文问题 → 英文材料 → 带引用的答案 → 逐条核对。
- 拒答路径是活的（§3），不是文档上写着而已。
- 引用校验对**伪造**是有效的：5/8 次诱导出来的假引文全被抓到（§6.2）。
- 服务层和 CLI 是**同一个系统**：`status`/`problems` 同源，缓存命中不假装花钱（§5）。

**没证明**

- ❌ **没证明答案普遍正确。** 演示一、二、五是能答的题；§4 那道题答错了。
  真·答对率只有一次人判（86%，rerank，n=28，±15 点），见 [README §5](../README.md#5-实测数字)。
- ❌ **没证明引用校验能保证可信。** 它只管"引文是不是伪造的"。
- ❌ **没证明它能处理"不知道"。** §4 说明：材料里没有答案时，它会用真引文编一个像样的答案。
  这是当前这套架构最明确的边界。
- ❌ **没证明速度可接受。** 13 秒/题（其中 10 秒是 CPU 重排）是硬约束，
  交互场景要么关重排，要么换 GPU。
