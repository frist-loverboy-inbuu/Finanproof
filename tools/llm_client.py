import hashlib
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

CACHE_PATH = ROOT / "data" / "cache" / "llm_cache.jsonl"


class LLMClient:
    def __init__(self, cache: bool = True, timeout: int = 120):
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
        self.cache_enabled = cache and os.getenv("LLM_CACHE", "on") != "off"
        self.timeout = timeout
        self.stats = {"calls": 0, "cache_hits": 0, "prompt_tokens": 0, "completion_tokens": 0}

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _cache_key(self, payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256((self.model + "|" + raw).encode("utf-8")).hexdigest()

    def _read_cache(self) -> dict:
        if not CACHE_PATH.exists():
            return {}
        cache = {}
        for line in CACHE_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                    cache[rec["key"]] = rec
                except json.JSONDecodeError:
                    continue
        return cache

    def chat(self, messages: list, tools: list | None = None, temperature: float = 0.0,
             max_tokens: int = 2048, prompt_version: str = "") -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        key = self._cache_key(payload)
        if self.cache_enabled:
            cached = self._read_cache().get(key)
            if cached:
                self.stats["cache_hits"] += 1
                return {"content": cached.get("content", ""), "reasoning": cached.get("reasoning", ""),
                        "tool_calls": cached.get("tool_calls"),
                        "usage": cached.get("usage", {}), "cached": True, "model": self.model}
        if not self.available:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY，且无可用缓存")
        last_exc = None
        data = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.timeout,
                )
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        if data is None:
            raise RuntimeError(f"LLM请求失败（已重试3次）: {last_exc}")
        msg = data["choices"][0]["message"]
        usage = data.get("usage", {})
        result = {
            "content": msg.get("content") or "",
            "reasoning": msg.get("reasoning_content") or "",
            "tool_calls": msg.get("tool_calls"),
            "usage": usage,
            "cached": False,
            "model": data.get("model", self.model),
        }
        self.stats["calls"] += 1
        self.stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.stats["completion_tokens"] += usage.get("completion_tokens", 0)
        if self.cache_enabled and (result["content"].strip() or result["tool_calls"]):
            rec = {"key": key, "model": self.model, "prompt_version": prompt_version,
                   "temperature": temperature, "content": result["content"],
                   "reasoning": result["reasoning"],
                   "tool_calls": result["tool_calls"], "usage": usage,
                   "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with CACHE_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return result

    def chat_json(self, messages: list, prompt_version: str = "", retries: int = 2, **kwargs):
        last_error = None
        for _ in range(retries + 1):
            out = self.chat(messages, prompt_version=prompt_version, **kwargs)
            text = (out.get("content") or "").strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            try:
                return json.loads(text), out
            except json.JSONDecodeError as e:
                last_error = (e, text[:200])
        raise RuntimeError(f"LLM未返回合法JSON: {last_error}")
