"""
多模态解析（可选依赖）
- ocr_image：本地 OCR（pytesseract + tesseract 引擎）
- describe_image_with_vlm：多模态大模型理解图片（OpenAI 兼容 image_url）
- extract_tables_pdf：PDF 表格抽取（pdfplumber）
任一依赖缺失时抛出带安装指引的异常，主流程不受影响。
"""
import base64
from typing import Dict, List

from ..config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)


def ocr_image(image_path: str, lang: str = "chi_sim+eng") -> str:
    """本地 OCR 识别图片文字"""
    try:
        import pytesseract
        from PIL import Image

        return pytesseract.image_to_string(Image.open(image_path), lang=lang)
    except ImportError as e:
        raise ImportError(
            "OCR 需要安装 pytesseract、Pillow，并在系统安装 tesseract-ocr 引擎"
        ) from e


async def describe_image_with_vlm(
    image_path: str,
    prompt: str = "请描述这张图片的内容，如有文字请识别，如有表格请结构化输出。",
) -> str:
    """用多模态大模型理解图片"""
    ext = image_path.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "png")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
    resp = await client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}},
                ],
            }
        ],
        max_tokens=600,
    )
    return resp.choices[0].message.content or ""


def extract_tables_pdf(pdf_path: str) -> List[Dict]:
    """抽取 PDF 中所有表格，返回 [{page, rows}]"""
    try:
        import pdfplumber
    except ImportError as e:
        raise ImportError("表格抽取需要安装 pdfplumber") from e

    tables: List[Dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            for rows in page.extract_tables():
                tables.append({"page": i, "rows": rows})
    return tables
