# -*- coding: utf-8 -*-
from reranking import Reranker


class TestNormalizeScores:
    def test_normalize_basic(self):
        values = [0.2, 0.8, 0.5]
        result = Reranker._normalize_scores(values)
        assert result[0] == 0.0
        assert result[1] == 1.0
        assert 0 < result[2] < 1.0

    def test_normalize_equal(self):
        values = [0.5, 0.5, 0.5]
        result = Reranker._normalize_scores(values)
        assert result == [0.5, 0.5, 0.5]

    def test_normalize_empty(self):
        assert Reranker._normalize_scores([]) == []

    def test_normalize_single(self):
        result = Reranker._normalize_scores([1.0])
        assert result == [0.5]
