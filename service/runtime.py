"""进程内的装配与复用 —— 索引、检索器、缓存、并发闸门。

── 流水线里的位置 ──

    scripts/ask.py      CLI 入口：一次进程问一句，每次都要重新装配
    service/api.py      HTTP 入口：一个进程问很多句            ← 本文件服务它
    scripts/eval_*.py   评测入口：一次进程跑一批，中间复用检索器

    ★ 三个入口的共同点：**检索器在循环外建一次**。
      CLI 那边是"每问一句重建一次重排器"的教训（scripts/ask.py 里那段大写注释），
      HTTP 这边更狠：如果每个请求都 build_retriever，13 秒里会有 1~2 秒
      花在【造一个一模一样的对象】上，而且不报错、不告警。

── 产品 / 外壳 ──

    本文件【属于外壳】。它做的三件事（装一次、缓存、限流）都是
    "这个进程怎么服务请求"，不是"这个系统怎么回答问题"。
    后者在 paper_rag/pipeline.py —— 两边调的是同一个 ask()。

── 为什么不在这里加任何判断 ──

    比如"检索分数低于 0.3 就拒答"这种想法，看起来很适合放这一层，
    但一旦放了：CLI 没有、评测没有、只有 HTTP 有 ——
    下一个量出来的数字就和生产不是一回事了。
    ★ 这个仓库在 S5-1 / S5-2 / S5-6 上各栽过一次「评测和生产不是同一套实现」。
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict

from paper_rag.config import EMB_MODEL, EXPAND_ENABLED, PROCESSED_DIR, TOP_K
from paper_rag.embed import make_client
from paper_rag.index import load
from paper_rag.logger import setup as setup_logging
from paper_rag.pipeline import ask as pipeline_ask
from paper_rag.pipeline import build_retriever

# ── 三个服务侧常量。它们【不】进 paper_rag/config.py：那里放的是"系统怎么想问题"，
#    这里放的是"这个进程怎么扛请求"。混在一起，改并发数就会看起来像改了检索策略。

# Ollama 默认同时只跑一个生成请求；重排是 CPU 密集的。
# 开两个能盖住"一个在等模型、一个在重排"的空档，再高只会让两边都变慢。
MAX_CONCURRENT_ASKS = 2

# 同一句话在 1 小时内重复问，直接给缓存。演示时"再点一次"不该等第二个 13 秒。
# ⚠️ 缓存键包含模型名吗？不包含 —— 索引和模型都是【进程启动时】定的，
#    进程不重启就不会变。跨进程复用的是磁盘上的索引，不是这份缓存。
CACHE_TTL_SECONDS = 3600
CACHE_MAX_ENTRIES = 128


class Runtime:
    """一次装配，长期复用。线程安全（只用在这一个进程里）。"""

    def __init__(self) -> None:
        setup_logging()

        t0 = time.perf_counter()
        payload = json.loads((PROCESSED_DIR / "chunks.json").read_text(encoding="utf-8"))
        self.chunks: list[dict] = payload["chunks"]

        # model=EMB_MODEL 会让 load() 核对索引是不是这个模型建的。
        # 核不上直接抛 —— 服务起不来，比"起来了但答非所问"好。
        self.vectors, self.ids = load(model=EMB_MODEL)
        self.client = make_client()

        # ★ 两个检索器都建出来。
        #   dense 那个不含重排器，构造是微秒级的；rerank 那个【只建对象、不加载权重】——
        #   CrossEncoderReranker 是懒加载的（见 rerank._ensure_model），
        #   所以这里 0.4 秒就起来了，第一次真用到重排时才付那 568M 的加载时间。
        #   两个都【预先建好】是为了让 /health 能如实报出名字 ——
        #   而不是等第一个请求来了才发现检索器根本建不出来。
        self._retrievers = {
            "rerank": build_retriever(self.client, EMB_MODEL, self.vectors, self.ids,
                                      self.chunks),
            "dense": build_retriever(self.client, EMB_MODEL, self.vectors, self.ids,
                                     self.chunks, enabled=False),
        }
        self.load_seconds = round(time.perf_counter() - t0, 2)
        self.started_at = time.time()

        self._cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._key_locks: dict[str, threading.Lock] = {}
        self._meta = threading.Lock()
        self._gate = threading.BoundedSemaphore(MAX_CONCURRENT_ASKS)

        self.n_asks = 0
        self.n_cache_hits = 0
        self.n_failures = 0

    # ── 只读信息（给 /health 和界面用）────────────────────────────────

    @property
    def retriever_names(self) -> dict[str, str]:
        return {variant: rt.name for variant, rt in self._retrievers.items()}

    def health(self) -> dict:
        return {
            "ok": True,
            "chunks": len(self.chunks),
            "dim": int(self.vectors.shape[1]) if getattr(self.vectors, "ndim", 0) == 2 else None,
            "emb_model": EMB_MODEL,
            "retrievers": self.retriever_names,
            "load_seconds": self.load_seconds,
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "n_asks": self.n_asks,
            "n_cache_hits": self.n_cache_hits,
            "n_failures": self.n_failures,
        }

    # ── 一次问答 ──────────────────────────────────────────────────────

    def ask(self, question: str, *, k: int = TOP_K, expand: bool | None = None,
            variant: str = "rerank") -> dict:
        """问一句。返回 pipeline.ask() 的结果，外加 "cached"。

        ★ 这里【不】加工 status / problems / repairs —— 原样透传。
          一旦在服务层"顺手整理一下"，CLI 和 HTTP 的语义就开始分叉。
        """
        if variant not in self._retrievers:
            raise ValueError(f"未知检索器 {variant!r}，只有 {sorted(self._retrievers)}")

        use_expand = EXPAND_ENABLED if expand is None else bool(expand)
        key = f"{variant}|k={k}|expand={int(use_expand)}|{question.strip()}"

        hit = self._cache_get(key)
        if hit is not None:
            return {**hit, "cached": True}

        # ★ single-flight：同一句话并发进来时，只有一个真去算。
        #   没有这一层，演示时"连点两下"会同时跑两次 13 秒的任务，
        #   而两次的答案还可能不一样（temperature 不为 0）——
        #   看起来像随机故障，其实是自己撞自己。
        lock = self._key_lock(key)
        with lock:
            hit = self._cache_get(key)
            if hit is not None:
                return {**hit, "cached": True}

            with self._gate:
                with self._meta:
                    self.n_asks += 1
                try:
                    result = pipeline_ask(
                        self.client, question, self.chunks, self.vectors, self.ids,
                        k=k, expand=use_expand, retriever=self._retrievers[variant],
                    )
                except Exception:
                    with self._meta:
                        self.n_failures += 1
                    raise

            self._cache_put(key, result)
            return {**result, "cached": False}

    # ── 缓存 ──────────────────────────────────────────────────────────

    def _cache_get(self, key: str) -> dict | None:
        with self._meta:
            item = self._cache.get(key)
            if item is None:
                return None
            ts, value = item
            if time.monotonic() - ts > CACHE_TTL_SECONDS:
                # 过期就删。【不是】返回旧的再刷新 —— 那等于缓存永不过期。
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            self.n_cache_hits += 1
            return value

    def _cache_put(self, key: str, value: dict) -> None:
        with self._meta:
            self._cache[key] = (time.monotonic(), value)
            self._cache.move_to_end(key)
            # 满了就丢最久没用过的。★ 不按时间丢：刚写进去的那条可能正是
            # 用户马上要连点的，按时间丢会把它扔掉。
            while len(self._cache) > CACHE_MAX_ENTRIES:
                self._cache.popitem(last=False)

    def _key_lock(self, key: str) -> threading.Lock:
        with self._meta:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = self._key_locks[key] = threading.Lock()
            return lock

    # ⚠️ 已知边界：_key_locks 只增不减（每句不同的问题一个锁）。
    #    要清掉它得给锁带引用计数 —— 否则"捡走一个正被等待的锁"会让
    #    同一句话被算两遍（不会算错，只是白算一次）。
    #    演示服务里问题数是有界的，先不做；对外长跑要补。

