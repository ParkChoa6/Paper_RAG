# S8-1 · 后端：把 pipeline.ask() 包成 HTTP

> 日期：2026-11-19 · 状态：✅ 已跑通并逐条验证
> 前置：Stage 5 收尾（S5-10 判卷表 / S5-11 编号修正 / S5-12 重跑）

---

## 0. 流水线里的位置

```
   浏览器 / Streamlit
        │  HTTP JSON
        ▼
  ┌───────────────────────────────────────────┐
  │  service/api.py   FastAPI  ← 本步          │
  │    /api/health  /api/questions  /api/ask   │
  └───────────────────────────────────────────┘
        │  调方法
        ▼
  ┌───────────────────────────────────────────┐
  │  service/runtime.py  Runtime               │
  │    启动时装配一次：chunks / vectors / ids   │
  │    / ollama client / 两个检索器             │
  │    再加：TTL 缓存 + 单飞锁 + 并发上限        │
  └───────────────────────────────────────────┘
        │  ask()
        ▼
  paper_rag/pipeline.py   ← 产品代码，一行没改
```

### 产品 / 外壳 的分界

| 层 | 是什么 | 允许做什么 | 不允许做什么 |
|---|---|---|---|
| `paper_rag/` | **产品** | 检索、生成、校验、判断 status | 不 import web 框架、不 print |
| `scripts/` | **脚手架** | argparse、打表、写文件 | 不放业务判断 |
| `service/` | **外壳** | 参数校验、转述成 JSON、记日志 | **不做任何判断** |

★ 外壳的三条红线（写进 `service/api.py` 的 docstring 里了）：

1. **不判 status** —— `answered / refused / suspect / parse_failed` 只由 `pipeline._judge` 产生。
2. **不判 problems** —— 报几条、报什么，来自 `cite.verify`。
3. **不修编号** —— `repair_indices` 在 pipeline 里跑过，外壳只转述 `repairs`。

> 外壳一旦开始"顺手修一下"，界面看到的就和 CLI 看到的不是同一个系统，
> 而且**不会有任何东西报错** —— 本仓库反复踩过这一类（见 ROADMAP 规矩 1）。

---

## 1. 新增了什么

| 文件 | 作用 |
|---|---|
| `service/__init__.py` | 定角色：这一层是外壳，不是产品 |
| `service/runtime.py` | 进程内唯一的一份装配 + 缓存 + 并发闸 |
| `service/api.py` | FastAPI 路由 + pydantic 请求/响应模型 |
| `requirements.txt` | 新增 Stage 8 一节：fastapi / uvicorn / streamlit / httpx |

**没改的**：`paper_rag/*` 一个字没动（除了 S5-11 的编号修正，那是 Stage 5 的活），
`scripts/*` 没动。这一层是**加法**。

---

## 2. 为什么这么写

### 2.1 为什么用 lifespan 而不是模块级 `Runtime()`

模块级会在 **import 的瞬间**就开始加载 —— 包括：

- `uvicorn --reload` 的**每一次**热重载（改一行 CSS 就等一次模型加载）；
- 任何"我只是 import 一下看看"的工具、IDE 的自动补全/类型检查。

启动期的活留给启动期：`lifespan` 进 → 装配，`yield` → 服务，退出 → 清理。

### 2.2 为什么显式写响应模型，而不是 `return result`

`pipeline.ask()` 返回的是**内部结构** —— `retrieved` 里塞着整个 chunk 字典。
直接返回 = 把内部 schema 变成接口契约：以后改 chunk 的字段名，
API 的形状会**静默**跟着变，前端在某个字段上突然拿到 `undefined`。

显式 `AskResponse` 让"接口长什么样"有一处可读的定义，
也多了一层保护：多出去的字段不会漏给浏览器。

### 2.3 为什么 `/api/questions` 只回问题文本

`data/eval/queries.json` 里除了 `q`，还有 `targets`（正确 chunk）和 `why`（关键事实）。
把它们送进浏览器 = **把答案提前告诉用户**，演示就变成抄答案了。

★ 这也是一条通用的规矩：**演示用的接口，返回值要按"观众能看到什么"裁剪，
不是按"数据里有什么"**。

### 2.4 为什么要有缓存，而且是 TTL + 单飞

- **TTL 1 小时**：演示时同一个问题会被反复点。缓存让第二次变成 5 毫秒。
- **单飞锁**：同一个问题被**并发**点两次时，只跑一次，第二个等结果 ——
  否则两个请求各跑一遍 20 秒的重排，不如排队。
- **128 条上限**：缓存是"方便"，不是"存储"。满了就丢最旧的，
  不要让它变成一个悄悄吃内存的东西。

★ 缓存键是 `(question, k, expand, variant)` —— **把 k 和重排开关也算进去**。
  只按问题文本缓存的话，改 k 之后再问会拿到旧 k 的结果，
  而现象是"滑块没反应"。

### 2.5 为什么有并发闸（`BoundedSemaphore(2)`）

重排在 CPU 上跑，一次吃满十几个核。同时来 5 个请求 → 5 个 20 秒的活
抢同一批核 → 每个都变成 100 秒，**总吞吐还更差**。

闸的价值不是"限制用户"，是让排队这件事**可见**（请求会慢，但不会一起烂掉）。
数字 2 是按"重排吃满 CPU + 生成走 Ollama（另一个进程）"定的，换机器要重量。

---

## 3. 不应该怎么写

### 3.1 ❌ 在路由里 `from paper_rag.pipeline import ask` 然后自己拼流程

那样 `/api/ask` 和 `scripts/ask.py` 会各走一条路。今天一样，改一次就不一样了。

### 3.2 ❌ 把异常吞成 200 + 空答案

```python
except Exception:
    return {"answer": "", "status": "refused"}   # ← 绝对不要
```

把"服务炸了"伪装成"模型拒答"，是**最难查的一种假绿**。
外壳的错（500）和模型的错（refused / parse_failed）必须分开 ——
这也是 `pipeline.ask` 的 docstring 里那条"不许合并"的同一条理由。

### 3.3 ❌ `allow_origins=["*"]`

这个服务会调模型、吃 CPU。公网随便一个页面都能打的 API 不是"方便"，是"没锁"。
只放行本地前端（8501）。

### 3.4 ❌ 让前端 import `paper_rag`

只要前端能直接调库，界面看到的和 API 给出的就会分叉。见 §0 的三条红线。

---

## 4. 怎么验证它真的对了

全部是实测（2026-11-19 13:34 ~ 13:37，uvicorn 0.38.0 / fastapi 0.118.3）。

### 4.1 启动

```
INFO service.api | 就绪：1345 条 chunk，检索器 {...}，用时 0.42s
INFO: Uvicorn running on http://127.0.0.1:8000
```

★ 0.42s 是**不含**重排权重的（重排是懒加载）。第一次真正用到它时才加载。

### 4.2 `GET /api/health`

```json
{"ok": true, "chunks": 1345, "dim": 1024, "emb_model": "bge-m3:latest",
 "retrievers": {"rerank": "dense:bge-m3:latest:raw > ce:bge-reranker-v2-m3:cpu @pool50",
                "dense": "dense:bge-m3:latest:raw"},
 "load_seconds": 0.42, "uptime_seconds": 2.3,
 "n_asks": 0, "n_cache_hits": 0, "n_failures": 0}
```

### 4.3 `POST /api/ask`（dense 臂）

```
HTTP 200 · 2.4s · status=answered · cached=false
timings {'retrieve': 0.069, 'generate': 1.799, 'verify': 0.001, 'total': 1.869}
引用校验通过，used=[1]，citations=[1]
```

### 4.4 `POST /api/ask`（rerank 臂）

```
第一次  22.3s（含重排权重加载，检索 20.3s）
稳态    9.8 ~ 11.5s（检索 8.6 ~ 10.2s，生成 1.2 ~ 1.3s，校验 0.00s）
```

★ 和评测里 12.7 秒/题对得上。**慢的是重排，不是生成** ——
这个结论以前只活在评测脚本里，现在界面上一眼能看到。

### 4.5 缓存

```
同一问题第二次: 0.005s · cached=true · 日志写「缓存命中（本来要 22.3s：…）」
```

### 4.6 参数校验（pydantic 挡在业务之前）

```
{"question": "", "k": 5}   → 422
{"question": "x", "k": 99} → 422
```

★ 422 而不是 500：**调用方参数错了**和**服务坏了**必须是两种信号。

### 4.7 转述完整性

一次 rerank 回答里 `status / answer / used / citations / problems / repairs /
timings / materials / cached` 全部到位，`problems=1` 那条是模型真把
`O(st) = (et, es, r, t)` 抄丢了下标 —— 属于 verify 该报的，不是接口丢字段。

### 4.8 顺手修的两个日志噪音

| 现象 | 原因 | 处理 |
|---|---|---|
| 一次问答三行日志，两行是传输层 | ollama 客户端走 httpx，INFO 级 | `logging.getLogger("httpx").setLevel(WARNING)` |
| `Batches: 46%|████▌` 进度条糊进日志 | `CrossEncoder.predict` 默认开进度条 | `show_progress_bar=False`（不改分数，和 batch_size 同性质） |

★ 残留：`Loading weights: 100%|██████| 393/393` 还会出现一次，
来自 transformers 的加载日志。本步的判断是留着 —— 它算个信号
（"权重加载了"）。

> **2026-11-19 补记（S8-2）**：这条后来关掉了，见
> [`S8-2-ui.md` §4.6](S8-2-ui.md)。理由是"信号"这个说法站不住 ——
> `_load_model` 里本来就有 `logger.info("加载重排模型 …")` 和
> `logger.info("重排模型 … 已就绪")` 两句，**那条进度条是重复的**。
> ★ 顺带说明本表的问题：它叫「日志噪音已清」，但清的是
>   **当时跑一眼看得见的两条**。写着"已清"的地方，最好有人回头再跑一遍。

---

## 5. 你要补的概念

### 5.1 外壳 / 产品 的判据

> 换掉这一层，业务逻辑**一行都不用改** —— 那它才是外壳。

本步的检验方式：`service/` 里没有一行代码能"决定"一条回答的 status。
想验证的话，把 `service/` 整个删掉，`scripts/ask.py` 照常能用。

### 5.2 缓存键必须包含所有影响结果的输入

缓存键漏一个参数（比如 `k`），症状是"某个开关不生效"，
而且**只在缓存命中时复现** —— 冷启动测不出来。

### 5.3 单飞（single-flight）

并发相同 key 只算一次，其余等结果。它不是"优化"，
是让"两个用户同时问同一句"这件事**不变成两个 20 秒的 CPU 任务**。

---

## 6. 自测题

1. 如果 `Runtime` 改成模块级 `Runtime()`，`uvicorn --reload` 开发时会怎样？
   哪一类改动会变得无法忍受？
2. `/api/ask` 里把 `except ValueError` 也改成 500 会有什么后果？
   （提示：想想调用方看到 500 的第一反应是什么）
3. 缓存键里去掉 `rerank` 会出什么现象？为什么**冷启动测不出来**？
4. 并发闸从 2 改成 8，单请求会变快还是变慢？为什么总吞吐可能更差？
5. 如果前端的某一天开始直接 `import paper_rag`，最先出问题的会是什么？
   （提示：不是"架构不美"，是一次具体的、看不见的分叉）

---

## 7. 遗留

- `AskResponse` 里 `answer` / `note` 允许 `None`。前端必须处理 `None`，
  否则 `res["answer"][:200]` 会崩在 `parse_failed` 上（`service/ui.py` 已经处理）。
- 还没有鉴权。**这是本机演示，不打算暴露到局域网以外。**
- 没有持久化：重启一次，缓存和计数清零。
