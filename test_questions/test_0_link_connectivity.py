# -*- coding: utf-8 -*-
"""
第0层: 前后端链路连通性测试
- 验证后端 API 可达性
- 验证前端代理到后端的链路
- 验证 SSE 流式响应格式
- 验证响应字段与前端类型定义对齐

前置条件: 后端服务已启动 (uvicorn server:app --port 4000)
可选条件: 前端服务已启动 (vite dev --port 3000)

用法:
    python test_0_link_connectivity.py
    python test_0_link_connectivity.py --backend-only
    python test_0_link_connectivity.py --backend-url http://localhost:4000
"""

import json
import time
import argparse
from typing import List, Dict, Optional
from test_utils import save_results, print_summary, generate_report

try:
    import requests
except ImportError:
    print("需要安装 requests: pip3 install requests -i https://pypi.tuna.tsinghua.edu.cn/simple")
    raise


class LinkTester:
    """前后端链路连通性测试器"""

    def __init__(self, backend_url: str = "http://localhost:4000", frontend_url: str = "http://localhost:3000"):
        self.backend_url = backend_url.rstrip("/")
        self.frontend_url = frontend_url.rstrip("/")
        self.results: List[Dict] = []

    def _record(self, name: str, passed: bool, detail: str = "", elapsed: float = 0):
        self.results.append({
            "name": name,
            "passed": passed,
            "detail": detail,
            "elapsed": round(elapsed, 3),
        })
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name} ({elapsed:.3f}s) {detail}")

    def test_backend_health(self):
        """测试后端服务是否可达"""
        print("\n--- 测试后端服务可达性 ---")
        try:
            t0 = time.time()
            resp = requests.get(f"{self.backend_url}/api/companies", timeout=10)
            elapsed = time.time() - t0
            self._record(
                "后端服务可达",
                resp.status_code == 200,
                f"status={resp.status_code}",
                elapsed,
            )
            return resp.status_code == 200
        except requests.ConnectionError:
            self._record("后端服务可达", False, "连接失败，请确认后端已启动")
            return False
        except Exception as e:
            self._record("后端服务可达", False, str(e))
            return False

    def test_companies_api(self):
        """测试 GET /api/companies"""
        print("\n--- 测试公司列表API ---")
        try:
            t0 = time.time()
            resp = requests.get(f"{self.backend_url}/api/companies", timeout=10)
            elapsed = time.time() - t0
            data = resp.json()

            is_list = isinstance(data, list)
            has_items = len(data) > 0
            passed = is_list and has_items

            self._record(
                "GET /api/companies",
                passed,
                f"返回{len(data)}个公司" if is_list else f"返回类型异常: {type(data).__name__}",
                elapsed,
            )
            return data if passed else []
        except Exception as e:
            self._record("GET /api/companies", False, str(e))
            return []

    def test_documents_api(self):
        """测试 GET /api/documents"""
        print("\n--- 测试文档列表API ---")
        try:
            t0 = time.time()
            resp = requests.get(f"{self.backend_url}/api/documents", timeout=10)
            elapsed = time.time() - t0
            data = resp.json()

            is_list = isinstance(data, list)
            has_items = len(data) > 0
            passed = is_list and has_items

            if is_list and has_items:
                first = data[0]
                required_keys = {"file_name", "company_name", "report_type", "report_year"}
                has_keys = required_keys.issubset(first.keys())
                self._record(
                    "GET /api/documents",
                    has_keys,
                    f"返回{len(data)}个文档, 字段完整={has_keys}",
                    elapsed,
                )
            else:
                self._record(
                    "GET /api/documents",
                    passed,
                    f"返回{len(data)}个文档" if is_list else f"返回类型异常",
                    elapsed,
                )
            return data if is_list else []
        except Exception as e:
            self._record("GET /api/documents", False, str(e))
            return []

    def test_retrieve_api(self):
        """测试 POST /api/retrieve"""
        print("\n--- 测试检索API ---")
        try:
            t0 = time.time()
            resp = requests.post(
                f"{self.backend_url}/api/retrieve",
                json={"question": "中芯国际2025年一季度营收", "company": "", "top_n": 3},
                timeout=30,
            )
            elapsed = time.time() - t0
            data = resp.json()

            has_chunks = "chunks" in data and isinstance(data["chunks"], list)
            has_elapsed = "elapsed" in data
            passed = has_chunks and has_elapsed

            chunk_count = len(data.get("chunks", []))
            self._record(
                "POST /api/retrieve",
                passed,
                f"返回{chunk_count}个chunks, 含elapsed={has_elapsed}",
                elapsed,
            )

            if has_chunks and chunk_count > 0:
                first_chunk = data["chunks"][0]
                required_keys = {"source", "page", "text", "score"}
                has_keys = required_keys.issubset(first_chunk.keys())
                self._record(
                    "检索结果字段完整性",
                    has_keys,
                    f"chunk字段: {list(first_chunk.keys())}",
                )

            return data if passed else {}
        except Exception as e:
            self._record("POST /api/retrieve", False, str(e))
            return {}

    def test_answer_stream_api(self):
        """测试 POST /api/answer/stream (SSE流式响应)"""
        print("\n--- 测试流式问答API ---")
        try:
            t0 = time.time()
            resp = requests.post(
                f"{self.backend_url}/api/answer/stream",
                json={
                    "question": "中芯国际2025年一季度的销售收入是否超过22亿美元？",
                    "type": "boolean",
                    "company": "",
                    "use_rerank": True,
                    "top_n": 3,
                },
                headers={"Accept": "text/event-stream"},
                timeout=120,
                stream=True,
            )

            events = []
            event_types = set()
            result_data = None

            buffer = ""
            for chunk in resp.iter_content(chunk_size=1024, decode_unicode=True):
                if chunk is None:
                    continue
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                        events.append(event)
                        event_types.add(event.get("type", ""))
                        if event.get("type") == "result":
                            result_data = event.get("data", {})
                    except json.JSONDecodeError:
                        pass

            elapsed = time.time() - t0

            has_step = "step" in event_types
            has_token = "token" in event_types
            has_result = "result" in event_types

            self._record(
                "POST /api/answer/stream SSE格式",
                has_step and has_token and has_result,
                f"事件类型: {sorted(event_types)}",
                elapsed,
            )

            if result_data:
                required_keys = {"final_answer", "relevant_pages", "context_docs"}
                has_keys = required_keys.issubset(result_data.keys())
                self._record(
                    "流式结果字段完整性",
                    has_keys,
                    f"result字段: {list(result_data.keys())}",
                )

                if "context_docs" in result_data and result_data["context_docs"]:
                    doc = result_data["context_docs"][0]
                    doc_keys = set(doc.keys())
                    expected_doc_keys = {"source", "page", "text", "score"}
                    doc_match = expected_doc_keys.issubset(doc_keys)
                    self._record(
                        "context_docs字段与前端Chunk类型对齐",
                        doc_match,
                        f"doc字段: {sorted(doc_keys)}",
                    )

            return result_data
        except Exception as e:
            self._record("POST /api/answer/stream", False, str(e))
            return None

    def test_frontend_proxy(self):
        """测试前端代理到后端的链路"""
        print("\n--- 测试前端代理链路 ---")
        try:
            t0 = time.time()
            resp = requests.get(f"{self.frontend_url}/api/companies", timeout=10)
            elapsed = time.time() - t0

            passed = resp.status_code == 200
            self._record(
                "前端代理 -> 后端",
                passed,
                f"status={resp.status_code}",
                elapsed,
            )
            return passed
        except requests.ConnectionError:
            self._record("前端代理 -> 后端", False, "前端服务未启动或代理未配置")
            return False
        except Exception as e:
            self._record("前端代理 -> 后端", False, str(e))
            return False

    def run(self, backend_only: bool = False):
        """运行全部链路测试"""
        print("=" * 60)
        print("  第0层: 前后端链路连通性测试")
        print("=" * 60)

        backend_ok = self.test_backend_health()
        if not backend_ok:
            print("\n后端不可达，跳过后续测试")
            print_summary(self.results, "链路连通性测试 (后端不可达)")
            generate_report(self.results, "链路连通性测试", "test_0_results.json")
            return self.results

        self.test_companies_api()
        self.test_documents_api()
        self.test_retrieve_api()
        self.test_answer_stream_api()

        if not backend_only:
            self.test_frontend_proxy()

        print_summary(self.results, "链路连通性测试")
        generate_report(self.results, "链路连通性测试", "test_0_results.json")
        return self.results


def main():
    parser = argparse.ArgumentParser(description="第0层: 前后端链路连通性测试")
    parser.add_argument("--backend-url", default="http://localhost:4000", help="后端地址")
    parser.add_argument("--frontend-url", default="http://localhost:3000", help="前端地址")
    parser.add_argument("--backend-only", action="store_true", help="仅测试后端(跳过前端代理测试)")
    args = parser.parse_args()

    tester = LinkTester(
        backend_url=args.backend_url,
        frontend_url=args.frontend_url,
    )
    tester.run(backend_only=args.backend_only)


if __name__ == "__main__":
    main()
