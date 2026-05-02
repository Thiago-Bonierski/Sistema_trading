"""
Script de demonstração das melhorias implementadas.

Mostra como usar os novos módulos e funcionalidades.
"""
import sys
from pathlib import Path

# Adicionar diretório atual ao path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

# Importar módulos refatorados
import config
from database import db_manager, init_database, salvar_cotacao
from equity import EquityManager, format_currency, format_percentage
from logging_config import setup_logging, log_trade_execution
from market_regime import analyze_regime
from position_manager import PositionManager
from utils.maintenance import run_maintenance, get_disk_usage_summary


def demo_logging():
    """Demonstra sistema de logging profissional."""
    print("\n" + "="*60)
    print("1️⃣  DEMONSTRAÇÃO: LOGGING PROFISSIONAL")
    print("="*60)
    
    logger = setup_logging("demo", "DEBUG")
    
    logger.debug("Mensagem de debug (desenvolvimento)")
    logger.info("Mensagem informativa (operação normal)")
    logger.warning("Alerta (algo suspeito)")
    logger.error("Erro (falha recuperável)")
    logger.critical("Crítico (falha grave)")
    
    print(f"\n✅ Logs salvos em: {config.LOG_DIR / 'demo.log'}")


def demo_config():
    """Demonstra uso de configurações centralizadas."""
    print("\n" + "="*60)
    print("2️⃣  DEMONSTRAÇÃO: CONFIGURAÇÕES CENTRALIZADAS")
    print("="*60)
    
    print(f"\n📊 Parâmetros de Trading:")
    print(f"  • Stop-Loss: {config.DEFAULT_STOP_LOSS_PCT:.1%}")
    print(f"  • Take-Profit: {config.DEFAULT_TAKE_PROFIT_PCT:.1%}")
    print(f"  • Max Position Age (NORMAL): {config.MAX_POSITION_AGE_TICKS['NORMAL']} ticks")
    
    print(f"\n🛡️  Limites de Risco:")
    print(f"  • Drawdown Limit: {config.EQUITY_DRAWDOWN_LIMIT:.1%}")
    print(f"  • Daily Loss Limit: {config.DAILY_LOSS_LIMIT:.1%}")
    print(f"  • Kill-Switch Duration: {config.KILL_SWITCH_HOURS}h")
    
    print(f"\n📈 Detecção de Regime:")
    print(f"  • Range Threshold: {config.RANGE_THRESHOLD}")
    print(f"  • Slope Threshold: {config.SLOPE_THRESHOLD_LARGE}")
    print(f"  • Chaos Volatility: {config.CHAOS_VOLATILITY_THRESHOLD}")
    
    print("\n✅ Todos os magic numbers agora estão em config.py!")


def demo_database():
    """Demonstra uso thread-safe do banco de dados."""
    print("\n" + "="*60)
    print("3️⃣  DEMONSTRAÇÃO: BANCO DE DADOS THREAD-SAFE")
    print("="*60)
    
    # Inicializar banco
    init_database()
    print("\n✅ Banco inicializado com índices otimizados")
    
    # Salvar cotação
    salvar_cotacao(
        horario="14:30:00",
        preco=5.85,
        moeda="USD",
        recomendacao="COMPRA",
        regime="TENDENCIA_ALTA",
        engine="TrendFollowing",
        confidence=0.82,
        details="Forte momentum positivo",
        ml_score=0.75
    )
    print("✅ Cotação salva com sucesso (thread-safe)")
    
    # Buscar dados
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM cotacoes WHERE moeda = ? ORDER BY id DESC LIMIT 1",
            ("USD",)
        )
        row = cursor.fetchone()
        
        if row:
            print(f"\n📊 Última cotação USD:")
            print(f"  • Preço: R$ {row['preco']:.2f}")
            print(f"  • Recomendação: {row['recomendacao']}")
            print(f"  • Regime: {row['regime']}")


def demo_equity():
    """Demonstra gerenciamento de equity."""
    print("\n" + "="*60)
    print("4️⃣  DEMONSTRAÇÃO: EQUITY MANAGER")
    print("="*60)
    
    em = EquityManager(initial_capital=100000.0)
    
    print(f"\n💰 Capital inicial: {format_currency(em.current_equity)}")
    
    # Simular trades
    trades = [
        ("Trade 1: +R$ 5,000", 5000.0),
        ("Trade 2: -R$ 2,000", -2000.0),
        ("Trade 3: +R$ 8,000", 8000.0),
        ("Trade 4: -R$ 3,000", -3000.0),
    ]
    
    for description, pnl in trades:
        em.update_equity(pnl)
        print(f"\n{description}")
        print(f"  → Equity: {format_currency(em.current_equity)}")
        print(f"  → Drawdown: {format_percentage(em.get_current_drawdown())}")
    
    # Resumo final
    summary = em.get_summary()
    print(f"\n📊 RESUMO FINAL:")
    print(f"  • Equity Atual: {format_currency(summary['current_equity'])}")
    print(f"  • Retorno Total: {summary['total_return_pct']:.2f}%")
    print(f"  • Max Drawdown: {summary['max_drawdown_pct']:.2f}%")
    print(f"  • Total de Trades: {summary['trade_count']}")


def demo_market_regime():
    """Demonstra detecção de regime de mercado."""
    print("\n" + "="*60)
    print("5️⃣  DEMONSTRAÇÃO: DETECÇÃO DE REGIME")
    print("="*60)
    
    # Gerar dados de teste
    scenarios = [
        ("Tendência de Alta", [100 + i*0.5 for i in range(35)]),
        ("Tendência de Baixa", [130 - i*0.5 for i in range(35)]),
        ("Consolidação", [100 + (i % 3) * 0.1 for i in range(35)]),
    ]
    
    for name, prices_list in scenarios:
        prices = pd.Series(prices_list)
        result = analyze_regime(prices)
        
        print(f"\n📈 Cenário: {name}")
        print(f"  • Regime Detectado: {result['regime']}")
        print(f"  • Slope: {result['slope']:.4f}")
        print(f"  • Volatility Ratio: {result['volatility_ratio']:.2f}")
        print(f"  • Momentum: {result['momentum']:.4f}")


def demo_maintenance():
    """Demonstra rotina de manutenção."""
    print("\n" + "="*60)
    print("6️⃣  DEMONSTRAÇÃO: MANUTENÇÃO DO SISTEMA")
    print("="*60)
    
    # Uso de disco
    usage = get_disk_usage_summary()
    print("\n📊 Uso de Disco:")
    for key, value in usage.items():
        print(f"  • {key}: {value:.2f} MB")
    
    print("\n🧹 Executando manutenção...")
    stats = run_maintenance()
    
    print(f"\n✅ Manutenção Concluída:")
    total_deleted = (
        stats['simulation_reports_deleted'] + 
        stats['training_reports_deleted']
    )
    total_freed = (
        stats['simulation_mb_freed'] + 
        stats['training_mb_freed']
    )
    
    print(f"  • Arquivos deletados: {total_deleted}")
    print(f"  • Espaço liberado: {total_freed:.2f} MB")
    print(f"  • Arquivos grandes encontrados: {stats['large_files_found']}")


def demo_position_manager():
    """Demonstra gerenciamento de posições."""
    print("\n" + "="*60)
    print("7️⃣  DEMONSTRAÇÃO: POSITION MANAGER")
    print("="*60)
    
    # Criar managers
    em = EquityManager(initial_capital=100000.0)
    pm = PositionManager(equity_manager=em)
    
    # Abrir posição
    position = pm.open_position(
        symbol="USD",
        side="COMPRA",
        price=5.85,
        regime="TENDENCIA_ALTA",
        engine="TrendFollowing",
        confidence=0.82,
        details="Momentum positivo forte",
        entry_tick=100
    )
    
    if position:
        print(f"\n✅ Posição Aberta:")
        print(f"  • Símbolo: USD")
        print(f"  • Side: {position.side}")
        print(f"  • Entry: R$ {position.entry_price:.2f}")
        print(f"  • Stop-Loss: R$ {position.stop_loss:.2f}")
        print(f"  • Take-Profit: R$ {position.take_profit:.2f}")
        print(f"  • Size: {format_currency(position.position_size)}")
        print(f"  • Confidence: {position.confidence:.2f}")
    
    # Simular take-profit
    result = pm.close_position(
        symbol="USD",
        exit_price=6.15,  # Acima do take-profit
        exit_regime="TENDENCIA_ALTA",
        reason="take_profit"
    )
    
    if result:
        print(f"\n🎯 Posição Fechada (Take-Profit):")
        print(f"  • PnL: {format_currency(result['pnl'])}")
        print(f"  • Duração: {result['duration_ticks']} ticks")
        print(f"  • Razão: {result['reason']}")


def main():
    """Executa todas as demonstrações."""
    print("\n")
    print("="*60)
    print("🚀 SISTEMA DE TRADING - DEMONSTRAÇÃO DE MELHORIAS")
    print("="*60)
    
    demo_logging()
    demo_config()
    demo_database()
    demo_equity()
    demo_market_regime()
    demo_position_manager()
    demo_maintenance()
    
    print("\n" + "="*60)
    print("✅ DEMONSTRAÇÃO CONCLUÍDA!")
    print("="*60)
    print("\nPróximos passos:")
    print("  1. Execute: pytest tests/ -v")
    print("  2. Leia: README.md")
    print("  3. Configure: config.py")
    print("  4. Inicie: python app.py")
    print("\n")


if __name__ == "__main__":
    main()
