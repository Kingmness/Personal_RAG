# -*- coding: utf-8 -*-
from pathlib import Path

from config import (
    PROJECT_ROOT,
    PDF_DATA_DIR,
    PARSED_MD_DIR,
    CHUNKED_JSON_DIR,
    FAISS_INDEX_DIR,
    BM25_INDEX_DIR,
    LOGS_DIR,
    METADATA_FILE,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    FAISS_WEIGHT,
    BM25_WEIGHT,
    RunConfig,
    PipelinePaths,
)


class TestPathConstants:
    def test_project_root_is_pra_dir(self):
        assert PROJECT_ROOT.name == "Backend"

    def test_data_dirs_under_data(self):
        assert PDF_DATA_DIR == PROJECT_ROOT / "data" / "pdf_data"
        assert PARSED_MD_DIR == PROJECT_ROOT / "data" / "parsed_md"
        assert CHUNKED_JSON_DIR == PROJECT_ROOT / "data" / "chunked_json"
        assert FAISS_INDEX_DIR == PROJECT_ROOT / "data" / "faiss_index"
        assert BM25_INDEX_DIR == PROJECT_ROOT / "data" / "bm25_index"

    def test_logs_dir_under_project(self):
        assert LOGS_DIR == PROJECT_ROOT / "logs"

    def test_metadata_file_under_project(self):
        assert METADATA_FILE == PROJECT_ROOT / "metadata.csv"

    def test_data_dirs_exist(self):
        for d in [PDF_DATA_DIR, PARSED_MD_DIR, CHUNKED_JSON_DIR,
                  FAISS_INDEX_DIR, BM25_INDEX_DIR, LOGS_DIR]:
            assert d.exists(), f"目录不存在: {d}"


class TestRunConfig:
    def test_defaults(self):
        cfg = RunConfig()
        assert cfg.chunk_size == CHUNK_SIZE
        assert cfg.chunk_overlap == CHUNK_OVERLAP
        assert cfg.faiss_weight == FAISS_WEIGHT
        assert cfg.bm25_weight == BM25_WEIGHT

    def test_override(self):
        cfg = RunConfig(chunk_size=500, faiss_weight=0.8)
        assert cfg.chunk_size == 500
        assert cfg.faiss_weight == 0.8


class TestPipelinePaths:
    def test_defaults(self):
        paths = PipelinePaths()
        assert paths.pdf_data == PDF_DATA_DIR
        assert paths.faiss_index == FAISS_INDEX_DIR

    def test_ensure_dirs(self, tmp_path):
        paths = PipelinePaths(
            parsed_md=tmp_path / "md",
            chunked_json=tmp_path / "json",
            faiss_index=tmp_path / "faiss",
            bm25_index=tmp_path / "bm25",
        )
        paths.ensure_dirs()
        assert (tmp_path / "md").exists()
        assert (tmp_path / "json").exists()
        assert (tmp_path / "faiss").exists()
        assert (tmp_path / "bm25").exists()
