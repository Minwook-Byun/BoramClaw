from __future__ import annotations

import unittest

from tools import semantic_web_snapshot


class TestSemanticSnapshotTool(unittest.TestCase):
    def test_run_parses_html(self) -> None:
        sample_html = """
        <html>
          <head><title>테스트 페이지</title></head>
          <body>
            <header>헤더</header>
            <main>
              <h1>첫 제목</h1>
              <p>본문 텍스트 내용</p>
              <a href="https://example.com/a">링크A</a>
            </main>
          </body>
        </html>
        """

        semantic_web_snapshot._fetch_html = lambda url, timeout_seconds: (sample_html, url)  # type: ignore[method-assign]
        out = semantic_web_snapshot.run({"url": "https://example.com"}, {})
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("title"), "테스트 페이지")
        self.assertGreaterEqual(len(out.get("headings", [])), 1)
        self.assertGreaterEqual(len(out.get("links", [])), 1)


if __name__ == "__main__":
    unittest.main()

