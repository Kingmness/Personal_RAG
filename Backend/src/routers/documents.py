# -*- coding: utf-8 -*-
"""
文档管理路由：上传、解析、分块、索引、元信息注册、状态查询、删除、校验
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from pydantic import BaseModel, Field

from config import (
    PDF_DATA_DIR, PARSED_MD_DIR, CHUNKED_JSON_DIR,
    FAISS_INDEX_DIR, BM25_INDEX_DIR, PROJECT_ROOT,
)
from dependencies import get_pipeline, get_write_lock, get_metadata_manager, get_logger

router = APIRouter()
_log = get_logger()


# ==================== 请求模型 ====================

class SingleDocRequest(BaseModel):
    file_name: str = Field(..., min_length=1)


# ==================== 工具函数 ====================

def safe_file_path(file_name: str, base_dir: Path) -> Path:
    """安全校验文件名，防止路径遍历攻击"""
    safe_name = Path(file_name).name
    if safe_name != file_name:
        raise HTTPException(status_code=400, detail=f"非法的文件名: {file_name}")
    result = (base_dir / safe_name).resolve()
    if not result.is_relative_to(base_dir.resolve()):
        raise HTTPException(status_code=400, detail="非法的文件路径")
    return result


# ==================== 端点 ====================

@router.get("/api/companies")
def get_companies():
    """获取所有公司列表"""
    mm = get_metadata_manager()
    return mm.get_company_names()


@router.get("/api/documents")
def get_documents(company: Optional[str] = None):
    """获取文档列表，包含所有已上传的PDF文件"""
    mm = get_metadata_manager()

    # 从 SQLite 读取已注册的文档
    registered_docs = {}
    for record in mm.list_all():
        registered_docs[record['file_name']] = record

    # 扫描 pdf_data 目录下所有 PDF 文件
    pdf_dir = PDF_DATA_DIR
    all_docs = []
    if pdf_dir.exists():
        for pdf_path in sorted(pdf_dir.glob("*.pdf")):
            file_name = pdf_path.name
            if company is None:
                if file_name in registered_docs:
                    doc = registered_docs[file_name]
                    all_docs.append({
                        'file_name': doc['file_name'],
                        'company_name': doc.get('company_name', ''),
                        'report_type': doc.get('report_type', ''),
                        'report_year': doc.get('report_year', ''),
                        'registered': True
                    })
                else:
                    all_docs.append({
                        'file_name': file_name,
                        'company_name': '',
                        'report_type': '',
                        'report_year': '',
                        'registered': False
                    })

    # 如果指定了公司，只显示该公司的文档
    if company is not None:
        all_docs = [doc for doc in all_docs if doc['company_name'] == company]

    return all_docs


@router.post("/api/upload")
async def upload_pdf(request: Request, file: UploadFile = File(...)):
    """上传PDF（仅保存文件，不自动处理）"""
    # 文件类型校验
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件上传")

    # 保存上传的文件
    pdf_dir = PDF_DATA_DIR
    pdf_dir.mkdir(exist_ok=True)
    pdf_path = safe_file_path(file.filename, pdf_dir)

    content = await file.read()

    # 文件大小校验（200MB 上限）
    max_size = 200 * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail="文件大小超过 200MB 限制")

    with open(pdf_path, "wb") as f:
        f.write(content)

    _log.info("文件上传成功: %s (%d bytes)", file.filename, len(content))
    return {"message": "文件上传成功", "file_name": file.filename}


@router.post("/api/parse")
async def parse_documents():
    """解析PDF文档"""
    try:
        pl = get_pipeline()
        wl = get_write_lock()
        async with wl:
            await asyncio.to_thread(pl.parse_pdfs)
        return {"message": "PDF解析完成"}
    except Exception as e:
        _log.error("解析失败: %s", e)
        raise HTTPException(status_code=500, detail="解析失败，请稍后重试")


@router.post("/api/chunk")
async def chunk_documents():
    """文本分块"""
    try:
        pl = get_pipeline()
        wl = get_write_lock()
        async with wl:
            await asyncio.to_thread(pl.chunk_reports)
        return {"message": "文本分块完成"}
    except HTTPException:
        raise
    except ValueError as e:
        _log.warning("分块前置条件不满足: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log.error("分块失败: %s", exc_info=True)
        raise HTTPException(status_code=500, detail=f"分块失败: {e}")
    except BaseException as e:
        _log.critical("分块发生严重错误: %s", exc_info=True)
        raise HTTPException(status_code=500, detail="分块发生严重错误，请稍后重试")


@router.post("/api/index")
async def index_documents():
    """构建索引"""
    try:
        pl = get_pipeline()
        wl = get_write_lock()
        async with wl:
            await asyncio.to_thread(pl.build_indices)
        return {"message": "索引构建完成"}
    except Exception as e:
        _log.error("索引构建失败: %s", e)
        raise HTTPException(status_code=500, detail="索引构建失败，请稍后重试")


@router.post("/api/metadata")
async def register_metadata():
    """注册元信息"""
    try:
        pl = get_pipeline()
        wl = get_write_lock()
        async with wl:
            await asyncio.to_thread(pl.register_metadata)
        return {"message": "元信息注册完成"}
    except Exception as e:
        _log.error("元信息注册失败: %s", e)
        raise HTTPException(status_code=500, detail="元信息注册失败，请稍后重试")


# ==================== 单个文档操作 ====================

@router.post("/api/parse/single")
async def parse_single_document(request: SingleDocRequest):
    """增量解析单个PDF文档"""
    try:
        pl = get_pipeline()
        pdf_dir = PDF_DATA_DIR
        pdf_path = safe_file_path(request.file_name, pdf_dir)
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail=f"文件不存在: {request.file_name}")
        wl = get_write_lock()
        async with wl:
            await asyncio.to_thread(pl.parse_single_pdf, pdf_path)
        return {"message": f"PDF解析完成: {request.file_name}"}
    except HTTPException:
        raise
    except Exception as e:
        _log.error("单个文档解析失败: %s", e)
        raise HTTPException(status_code=500, detail="解析失败，请稍后重试")


@router.post("/api/chunk/single")
async def chunk_single_document(request: SingleDocRequest):
    """增量分块单个文档"""
    try:
        pl = get_pipeline()
        safe_name = Path(request.file_name).name
        if safe_name != request.file_name:
            raise HTTPException(status_code=400, detail=f"非法的文件名: {request.file_name}")
        stem = Path(request.file_name).stem
        md_dir = PARSED_MD_DIR
        md_path = md_dir / f"{stem}.md"
        if not md_path.exists():
            raise HTTPException(status_code=404, detail=f"Markdown文件不存在: {md_path.name}")
        wl = get_write_lock()
        async with wl:
            await asyncio.to_thread(pl.chunk_single_report, md_path)
        return {"message": f"文本分块完成: {request.file_name}"}
    except HTTPException:
        raise
    except ValueError as e:
        _log.warning("分块前置条件不满足: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log.error("单个文档分块失败: %s", exc_info=True)
        raise HTTPException(status_code=500, detail=f"分块失败: {e}")
    except BaseException as e:
        _log.critical("分块发生严重错误: %s", exc_info=True)
        raise HTTPException(status_code=500, detail="分块发生严重错误，请稍后重试")


@router.post("/api/index/single")
async def index_single_document(request: SingleDocRequest):
    """增量构建单个文档的索引"""
    try:
        pl = get_pipeline()
        safe_name = Path(request.file_name).name
        if safe_name != request.file_name:
            raise HTTPException(status_code=400, detail=f"非法的文件名: {request.file_name}")
        stem = Path(request.file_name).stem
        json_dir = CHUNKED_JSON_DIR
        json_path = json_dir / f"{stem}.json"
        if not json_path.exists():
            raise HTTPException(status_code=404, detail=f"分块JSON文件不存在: {json_path.name}")
        wl = get_write_lock()
        async with wl:
            await asyncio.to_thread(pl.build_single_index, json_path)
        return {"message": f"索引构建完成: {request.file_name}"}
    except HTTPException:
        raise
    except Exception as e:
        _log.error("单个文档索引构建失败: %s", e)
        raise HTTPException(status_code=500, detail="索引构建失败，请稍后重试")


@router.post("/api/metadata/single")
async def register_single_metadata(request: SingleDocRequest):
    """增量注册单个文档的元信息"""
    try:
        pl = get_pipeline()
        pdf_dir = PDF_DATA_DIR
        pdf_path = safe_file_path(request.file_name, pdf_dir)
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail=f"文件不存在: {request.file_name}")
        wl = get_write_lock()
        async with wl:
            await asyncio.to_thread(pl.register_single_metadata, pdf_path)
        return {"message": f"元信息注册完成: {request.file_name}"}
    except HTTPException:
        raise
    except Exception as e:
        _log.error("单个文档元信息注册失败: %s", e)
        raise HTTPException(status_code=500, detail="元信息注册失败，请稍后重试")


@router.get("/api/document/status")
def get_document_status(file_name: str):
    """获取单个文档的处理状态"""
    safe_name = Path(file_name).name
    if safe_name != file_name:
        raise HTTPException(status_code=400, detail=f"非法的文件名: {file_name}")
    base_name = Path(file_name).stem
    pdf_dir = PDF_DATA_DIR
    md_dir = PARSED_MD_DIR
    json_dir = CHUNKED_JSON_DIR
    bm25_dir = BM25_INDEX_DIR
    faiss_dir = FAISS_INDEX_DIR

    status = {
        "file_name": file_name,
        "pdf_exists": (pdf_dir / file_name).exists(),
        "parsed_exists": (md_dir / f"{base_name}.md").exists(),
        "chunked_exists": (json_dir / f"{base_name}.json").exists(),
        "bm25_index_exists": (bm25_dir / f"{base_name}.pkl").exists(),
        "faiss_index_exists": (faiss_dir / f"{base_name}.faiss").exists(),
        "metadata_registered": False
    }

    # 从 SQLite 查询文档元信息
    mm = get_metadata_manager()
    record = mm.get_by_file_name(file_name)
    if record:
        status["metadata_registered"] = True
        status["company_name"] = record.get('company_name', '')
        status["report_type"] = record.get('report_type', '')
        status["report_year"] = record.get('report_year', '')

    return status


@router.delete("/api/document/{file_name}")
async def delete_document(request: Request, file_name: str):
    """删除文档及其所有关联文件（原子化：先收集再统一删除，失败时回滚）"""
    safe_name = Path(file_name).name
    if safe_name != file_name:
        raise HTTPException(status_code=400, detail=f"非法的文件名: {file_name}")

    base_name = Path(safe_name).stem
    base_dir = PROJECT_ROOT
    mm = get_metadata_manager()

    # 1. 收集所有待删文件路径
    files_to_delete = []
    pdf_path = safe_file_path(safe_name, base_dir / "pdf_data")
    if pdf_path.exists():
        files_to_delete.append(pdf_path)
    md_path = safe_file_path(f"{base_name}.md", base_dir / "parsed_md")
    if md_path.exists():
        files_to_delete.append(md_path)
    json_path = safe_file_path(f"{base_name}.json", base_dir / "chunked_json")
    if json_path.exists():
        files_to_delete.append(json_path)
    bm25_path = safe_file_path(f"{base_name}.pkl", base_dir / "bm25_index")
    if bm25_path.exists():
        files_to_delete.append(bm25_path)
    faiss_path = safe_file_path(f"{base_name}.faiss", base_dir / "faiss_index")
    if faiss_path.exists():
        files_to_delete.append(faiss_path)

    has_metadata = mm.get_by_file_name(safe_name) is not None

    if not files_to_delete and not has_metadata:
        raise HTTPException(status_code=404, detail=f"未找到与 {safe_name} 相关的任何文件")

    # 2. 将文件移到临时目录（而非直接删除），便于失败时回滚
    tmp_dir = Path(tempfile.mkdtemp(prefix="pra_delete_"))
    moved_files = []

    try:
        for f in files_to_delete:
            dest = tmp_dir / f.name
            shutil.move(str(f), str(dest))
            moved_files.append((f, dest))

        # 3. 删除 metadata 记录
        if has_metadata:
            mm.delete_by_file_name(safe_name)

        # 4. 全部成功，清理临时目录
        shutil.rmtree(tmp_dir, ignore_errors=True)
        deleted_files = [str(f) for f in files_to_delete]
        return {"message": f"文档 {safe_name} 已删除", "deleted_files": deleted_files}

    except Exception as e:
        # 回滚：将已移动的文件移回原位
        _log.error("删除文档 %s 失败，开始回滚: %s", safe_name, e)
        for original_path, tmp_path in moved_files:
            try:
                shutil.move(str(tmp_path), str(original_path))
            except Exception as rollback_err:
                _log.error("回滚文件 %s 失败: %s", original_path, rollback_err)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"删除文档失败: {e}")


@router.get("/api/validate")
def validate_consistency():
    """校验索引一致性"""
    mm = get_metadata_manager()
    result = mm.validate_consistency()
    return result
