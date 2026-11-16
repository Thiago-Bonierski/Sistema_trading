"""
Testes do pipeline de ML fim-a-fim.

Cobre:
- Contrato único de features (8 colunas, sem data leakage)
- Treino + inferência com alinhamento 100%
- duration_ticks removido (sem look-ahead bias)
- Recarregamento automático do modelo
- MLClassifier usa modelo real quando disponível
"""
import sys
import sqlite3
import tempfile
import os
import random
from pathlib import Path
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pandas as pd

from features import (
    FEATURE_COLUMNS, NUMERIC_FEATURES, CATEGORICAL_FEATURES,
    N_FEATURES, build_feature_row, build_training_frame,
)
import ml_training
import ml_classifier


class TestContratoFeatures:
    """Testes do contrato único de features."""

    def test_feature_columns_estaveis(self):
        """As colunas do contrato devem ser fixas e conhecidas."""
        assert N_FEATURES == 8
        assert FEATURE_COLUMNS == [
            "confidence", "slope", "momentum", "range_rel",
            "volatility_ratio", "regime", "engine", "action",
        ]
        assert len(NUMERIC_FEATURES) == 5
        assert len(CATEGORICAL_FEATURES) == 3

    def test_build_feature_row_retorna_contrato(self):
        """build_feature_row deve retornar exatamente as colunas do contrato."""
        row = build_feature_row(
            {"action": "COMPRA", "confidence": 0.8, "engine": "TrendFollowing"},
            {"regime": "TENDENCIA_ALTA", "slope": 0.01, "momentum": 0.02,
             "range_rel": 0.003, "volatility_ratio": 1.1},
        )
        assert set(row.keys()) == set(FEATURE_COLUMNS)
        assert row["confidence"] == 0.8
        assert row["slope"] == 0.01
        assert row["regime"] == "TENDENCIA_ALTA"
        assert row["action"] == "COMPRA"
        assert isinstance(row["regime"], str)
        assert isinstance(row["engine"], str)
        assert isinstance(row["action"], str)

    def test_sem_duration_ticks(self):
        """duration_ticks NÃO deve estar nas features (data leakage)."""
        assert "duration_ticks" not in FEATURE_COLUMNS
        assert "duration_ticks" not in NUMERIC_FEATURES
        assert "duration_ticks" not in CATEGORICAL_FEATURES


class TestMLPipelineFimAFim:
    """Testes de treino e inferência usando o mesmo contrato."""

    def _criar_banco_sintetico(self, n_trades=100, seed=7):
        """Cria banco temporário com trades sintéticos."""
        tmp = tempfile.mktemp(suffix='.db')
        conn = sqlite3.connect(tmp)
        conn.execute('''CREATE TABLE trade_history (
            id INTEGER PRIMARY KEY, symbol TEXT, side TEXT, entry_price REAL,
            exit_price REAL, entry_tick INTEGER, exit_tick INTEGER,
            entry_regime TEXT, exit_regime TEXT, engine TEXT, confidence REAL,
            pnl REAL, position_size REAL, duration_ticks INTEGER,
            reason TEXT, aggressiveness TEXT)''')
        rng = random.Random(seed)
        regimes = ['TENDENCIA_ALTA', 'TENDENCIA_BAIXA', 'CONSOLIDACAO']
        engines = ['TrendFollowing', 'MeanReversion', 'BreakoutMomentum']
        sides = ['COMPRA', 'VENDA']
        for i in range(n_trades):
            side = rng.choice(sides)
            entry = rng.uniform(90, 110)
            pnl = rng.uniform(-500, 500)
            conn.execute(
                '''INSERT INTO trade_history
                   (symbol,side,entry_price,exit_price,entry_tick,exit_tick,
                    entry_regime,exit_regime,engine,confidence,pnl,
                    position_size,duration_ticks,reason,aggressiveness)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('USD', side, entry, entry + pnl / 10000, i, i + 10,
                 rng.choice(regimes), 'TENDENCIA_ALTA', rng.choice(engines),
                 rng.uniform(0.5, 0.95), pnl, 10000.0, 10, 'take_profit', 'NORMAL'))
        conn.commit()
        conn.close()
        return tmp

    def test_treino_e_inferencia_alinhados(self):
        """O modelo treinado deve inferir com as mesmas 8 features do contrato."""
        import importlib
        importlib.reload(ml_training)
        importlib.reload(ml_classifier)
        tmp = self._criar_banco_sintetico(n_trades=120, seed=11)
        modelo_path = Path('/tmp/opencode/test_pipeline_model_alinhado.joblib')

        try:
            # Mockar db_manager para ler do banco temporário
            class FakeDB:
                def __init__(self, path):
                    self.path = path
                @contextmanager
                def get_connection(self):
                    c = sqlite3.connect(self.path)
                    try:
                        yield c; c.commit()
                    finally:
                        c.close()
            ml_training.db_manager = FakeDB(tmp)

            # Treinar com contrato único
            trainer = ml_training.MLTrainer(model_path=modelo_path)
            resultado = trainer.train_model()
            assert resultado['n_features'] == 8
            assert resultado['feature_columns'] == FEATURE_COLUMNS
            assert resultado['samples_trained'] + resultado['samples_tested'] > 0

            # Recarregar no classificador (instância fresca, caminho isolado)
            clf = ml_classifier.MLClassifier(model_path=modelo_path)
            assert clf.is_trained() is True

            # Inferência com o mesmo contrato de features
            sugestao = {
                'action': 'COMPRA', 'confidence': 0.82, 'engine': 'TrendFollowing',
                'regime_metrics': {
                    'regime': 'TENDENCIA_ALTA', 'slope': 0.01, 'momentum': 0.02,
                    'range_rel': 0.003, 'volatility_ratio': 1.1,
                },
            }
            score = clf.score_trade(sugestao)
            assert 0.0 <= score <= 1.0

            # Filtrar sinal
            filtrado = clf.filter_signal(sugestao, sugestao['regime_metrics'])
            assert 'ml_score' in filtrado
            assert abs(filtrado['ml_score'] - score) < 1e-10 or filtrado['ml_score'] == score

            # Verificar que o pipeline espera 8 features
            assert clf.model.n_features_in_ == 8

        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
            try:
                os.remove(modelo_path)
            except OSError:
                pass

    def test_dados_insuficientes_erro(self):
        """Deve levantar ValueError quando há poucos trades."""
        tmp = self._criar_banco_sintetico(n_trades=5, seed=1)
        try:
            class FakeDB:
                def __init__(self, path):
                    self.path = path
                @contextmanager
                def get_connection(self):
                    c = sqlite3.connect(self.path)
                    try:
                        yield c; c.commit()
                    finally:
                        c.close()
            ml_training.db_manager = FakeDB(tmp)
            trainer = ml_training.MLTrainer()
            with pytest.raises(ValueError):
                trainer.train_model()
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def test_sem_modelo_usa_heuristica(self):
        """Quando não há modelo, o classificador usa heurística sem quebrar."""
        # Caminho que não existe -> não carrega modelo
        clf = ml_classifier.MLClassifier(
            model_path=Path('/tmp/opencode/nao_existe_modelo_heuristica.joblib')
        )
        assert clf.is_trained() is False
        sugestao = {
            'action': 'COMPRA', 'confidence': 0.8, 'engine': 'TrendFollowing',
            'regime_metrics': {
                'regime': 'TENDENCIA_ALTA', 'slope': 0.01, 'momentum': 0.02,
                'range_rel': 0.003, 'volatility_ratio': 1.1,
            },
        }
        score = clf.score_trade(sugestao)
        assert 0.0 <= score <= 1.0
