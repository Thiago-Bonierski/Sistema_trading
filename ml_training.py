"""
Módulo de treinamento do modelo ML.

Treina classificador para filtrar sinais de trading baseado
em histórico de trades executados.

Features usadas:
- confidence: Confiança da engine (float)
- duration_ticks: Duração do trade (int)
- side_signal: Direção (COMPRA=1, VENDA=-1)
- entry_regime: Regime de entrada (categórica)
- engine: Engine que gerou sinal (categórica)

Target:
- pnl_positive: 1 se trade foi lucrativo, 0 caso contrário

Essas features são alinhadas com o ml_classifier.py para
garantir consistência entre treino e inference.
"""
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import logging

import pandas as pd

import config
from database import db_manager
from logging_config import setup_logging

# Imports opcionais de ML
try:
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    import joblib
    
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logging.warning(
        "scikit-learn ou joblib não disponível - "
        "treinamento ML não funcionará"
    )

# Configurar logging
logger = setup_logging("ml_training", config.LOG_LEVEL)


class MLTrainer:
    """
    Trainer para modelo ML de filtro de sinais.
    
    Carrega histórico de trades, processa features,
    treina modelo e salva para uso posterior.
    
    Attributes:
        db_path: Caminho do banco de dados
        model_path: Caminho para salvar modelo
    """
    
    def __init__(
        self,
        db_path: Path = config.DB_PATH,
        model_path: Path = config.ML_MODEL_PATH
    ):
        """
        Inicializa trainer.
        
        Args:
            db_path: Caminho do banco de dados
            model_path: Caminho para salvar modelo
        """
        self.db_path = db_path
        self.model_path = model_path
        
        logger.info(
            f"MLTrainer inicializado: "
            f"db={db_path}, model={model_path}"
        )
    
    def load_trade_history(self) -> pd.DataFrame:
        """
        Carrega histórico de trades do banco.
        
        Returns:
            DataFrame com trades executados
            
        Raises:
            Exception: Se erro ao acessar banco
        """
        query = "SELECT * FROM trade_history ORDER BY id"
        
        try:
            with db_manager.get_connection() as conn:
                df = pd.read_sql_query(query, conn)
            
            logger.info(f"Carregados {len(df)} trades do histórico")
            return df
            
        except Exception as e:
            logger.error(f"Erro ao carregar histórico: {e}", exc_info=True)
            raise
    
    def build_features(
        self,
        df: pd.DataFrame
    ) -> Tuple[Optional[pd.DataFrame], Optional[pd.Series]]:
        """
        Constrói features e target a partir do DataFrame.
        
        Features (alinhadas com ml_classifier.py):
        - confidence: Confiança da engine (float)
        - duration_ticks: Duração do trade (int)
        - side_signal: 1 para COMPRA, -1 para VENDA (int)
        - entry_regime: Regime de entrada (categórica -> one-hot)
        - engine: Engine que gerou o sinal (categórica -> one-hot)
        
        Target:
        - pnl_positive: 1 se lucro > 0, 0 caso contrário (int)
        
        Args:
            df: DataFrame com histórico de trades
            
        Returns:
            Tupla (X, y) com features e target, ou (None, None) se vazio
        """
        if df.empty:
            logger.warning("DataFrame vazio, não há dados para features")
            return None, None
        
        # Criar cópia para não modificar original
        df = df.copy()
        
        # Validar colunas necessárias
        required_cols = ["side", "confidence", "duration_ticks", "entry_regime", "engine", "pnl"]
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            logger.error(f"Colunas faltando no DataFrame: {missing}")
            return None, None
        
        # Feature engineering
        df["side_signal"] = df["side"].map({
            "COMPRA": 1,
            "VENDA": -1
        }).fillna(0)
        
        df["pnl_positive"] = (df["pnl"] > 0).astype(int)
        
        # Preencher valores nulos em categorias
        df["entry_regime"] = df["entry_regime"].fillna("DESCONHECIDO")
        df["engine"] = df["engine"].fillna("UNKNOWN")
        df["confidence"] = df["confidence"].fillna(0.5)
        df["duration_ticks"] = df["duration_ticks"].fillna(10)
        
        # Selecionar features numéricas e categóricas
        numeric_features = ["confidence", "duration_ticks", "side_signal"]
        categorical_features = ["entry_regime", "engine"]
        feature_columns = numeric_features + categorical_features
        
        # Preparar dados para o transformer
        X_numeric = df[numeric_features].astype(float)
        X_categorical = df[categorical_features].astype(str)
        
        X = pd.concat([X_numeric, X_categorical], axis=1)
        y = df["pnl_positive"]
        
        logger.debug(
            f"Features construídas: {len(X)} amostras, "
            f"{len(numeric_features)} numéricas + {len(categorical_features)} categóricas"
        )
        
        return X, y
    
    def train_model(self) -> Dict[str, Any]:
        """
        Treina modelo ML e salva em disco.
        
        Processo:
        1. Carrega histórico de trades
        2. Constrói features (numéricas + categóricas)
        3. Split train/test
        4. Treina LogisticRegression com preprocessamento
        5. Avalia performance
        6. Salva modelo com pipeline completo
        
        O pipeline salvo inclui:
        - ColumnTransformer (StandardScaler para numéricas, OneHotEncoder para categóricas)
        - LogisticRegression (modelo de classificação)
        
        Returns:
            Dicionário com resultados do treinamento:
            {
                'model_path': str,
                'test_score': float,
                'samples_trained': int,
                'samples_tested': int
            }
            
        Raises:
            RuntimeError: Se sklearn não disponível
            ValueError: Se dados insuficientes
        """
        if not ML_AVAILABLE:
            raise RuntimeError(
                "scikit-learn ou joblib não está instalado. "
                "Instale com: pip install scikit-learn joblib"
            )
        
        logger.info("Iniciando treinamento do modelo ML...")
        
        # Carregar dados
        df = self.load_trade_history()
        
        if df.empty:
            raise ValueError(
                "trade_history está vazio. "
                "Execute trades para gerar histórico."
            )
        
        if len(df) < config.MIN_TRADES_FOR_TRAINING:
            raise ValueError(
                f"Dados insuficientes: {len(df)} trades < "
                f"{config.MIN_TRADES_FOR_TRAINING} mínimo"
            )
        
        # Construir features
        X, y = self.build_features(df)
        
        if X is None or y is None:
            raise ValueError("Não foi possível montar features para treinamento")
        
        # Split train/test
        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=0.2,
            random_state=42
        )
        
        logger.info(
            f"Dataset split: train={len(X_train)}, test={len(X_test)}"
        )
        
        # Construir pipeline com suporte a features categóricas
        numeric_features = ["confidence", "duration_ticks", "side_signal"]
        categorical_features = ["entry_regime", "engine"]
        
        preprocessor = ColumnTransformer(
            transformers=[
                ("num", StandardScaler(), numeric_features),
                ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical_features)
            ]
        )
        
        pipeline = Pipeline([
            ("preprocessor", preprocessor),
            ("model", LogisticRegression(
                solver="lbfgs",
                max_iter=1000,
                random_state=42
            )),
        ])
        
        # Treinar
        logger.info("Treinando modelo...")
        pipeline.fit(X_train, y_train)
        
        # Avaliar
        score = pipeline.score(X_test, y_test)
        
        logger.info(f"Score no teste: {score:.4f}")
        
        # Salvar modelo
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(pipeline, str(self.model_path))
        
        logger.info(f"Modelo salvo em {self.model_path}")
        
        result = {
            "model_path": str(self.model_path),
            "test_score": float(score),
            "samples_trained": len(X_train),
            "samples_tested": len(X_test),
        }
        
        return result


if __name__ == "__main__":
    logger.info("Executando treinamento standalone...")
    
    trainer = MLTrainer()
    
    try:
        result = trainer.train_model()
        
        print("\n" + "="*60)
        print("TREINAMENTO CONCLUÍDO COM SUCESSO")
        print("="*60)
        print(f"\n📊 Resultados:")
        print(f"  • Modelo salvo: {result['model_path']}")
        print(f"  • Score de teste: {result['test_score']:.2%}")
        print(f"  • Amostras de treino: {result['samples_trained']}")
        print(f"  • Amostras de teste: {result['samples_tested']}")
        print("\n" + "="*60 + "\n")
        
    except Exception as exc:
        logger.error(f"Erro ao treinar modelo: {exc}", exc_info=True)
        
        print("\n" + "="*60)
        print("ERRO NO TREINAMENTO")
        print("="*60)
        print(f"\n❌ {exc}")
        print("\n" + "="*60 + "\n")
        
        raise
