"""
Utilitários de manutenção do sistema.

Limpeza de arquivos antigos, rotação de relatórios, etc.
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple

import config

logger = logging.getLogger(__name__)


def get_file_age_days(file_path: Path) -> int:
    """
    Retorna idade do arquivo em dias.
    
    Args:
        file_path: Caminho do arquivo
        
    Returns:
        Idade em dias
    """
    if not file_path.exists():
        return 0
    
    modified_time = datetime.fromtimestamp(file_path.stat().st_mtime)
    age = datetime.now() - modified_time
    return age.days


def get_file_size_mb(file_path: Path) -> float:
    """
    Retorna tamanho do arquivo em MB.
    
    Args:
        file_path: Caminho do arquivo
        
    Returns:
        Tamanho em megabytes
    """
    if not file_path.exists():
        return 0.0
    
    size_bytes = file_path.stat().st_size
    return size_bytes / (1024 * 1024)


def cleanup_old_reports(
    reports_dir: Path,
    keep_last: int,
    max_age_days: int,
    pattern: str = "*.json"
) -> Tuple[int, float]:
    """
    Remove relatórios antigos mantendo apenas os mais recentes.
    
    Usa duas estratégias:
    1. Manter apenas os últimos N arquivos
    2. Deletar arquivos mais velhos que X dias
    
    Args:
        reports_dir: Diretório com relatórios
        keep_last: Número de arquivos recentes a manter
        max_age_days: Idade máxima em dias
        pattern: Padrão de arquivos (ex: "*.json")
        
    Returns:
        Tupla (arquivos deletados, MB liberados)
    """
    if not reports_dir.exists():
        logger.warning(f"Diretório {reports_dir} não existe")
        return 0, 0.0
    
    # Listar todos os arquivos do padrão
    files = list(reports_dir.glob(pattern))
    
    if not files:
        logger.debug(f"Nenhum arquivo encontrado em {reports_dir}")
        return 0, 0.0
    
    # Ordenar por data de modificação (mais recentes primeiro)
    files_sorted = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)
    
    deleted_count = 0
    deleted_size_mb = 0.0
    
    for i, file_path in enumerate(files_sorted):
        should_delete = False
        reason = ""
        
        # Manter os N mais recentes
        if i >= keep_last:
            should_delete = True
            reason = f"excede limite de {keep_last} arquivos"
        
        # Deletar se muito antigo
        age_days = get_file_age_days(file_path)
        if age_days > max_age_days:
            should_delete = True
            reason = f"idade de {age_days} dias excede {max_age_days}"
        
        if should_delete:
            size_mb = get_file_size_mb(file_path)
            try:
                file_path.unlink()
                deleted_count += 1
                deleted_size_mb += size_mb
                logger.info(
                    f"Deletado: {file_path.name} "
                    f"({size_mb:.2f} MB, {reason})"
                )
            except Exception as e:
                logger.error(f"Erro ao deletar {file_path}: {e}")
    
    if deleted_count > 0:
        logger.info(
            f"Limpeza concluída: {deleted_count} arquivos deletados, "
            f"{deleted_size_mb:.2f} MB liberados"
        )
    
    return deleted_count, deleted_size_mb


def check_large_reports(
    reports_dir: Path,
    max_size_mb: float,
    pattern: str = "*.json"
) -> List[Tuple[Path, float]]:
    """
    Identifica relatórios anormalmente grandes.
    
    Args:
        reports_dir: Diretório com relatórios
        max_size_mb: Tamanho máximo aceitável em MB
        pattern: Padrão de arquivos
        
    Returns:
        Lista de tuplas (arquivo, tamanho_mb) dos arquivos grandes
    """
    if not reports_dir.exists():
        return []
    
    large_files = []
    
    for file_path in reports_dir.glob(pattern):
        size_mb = get_file_size_mb(file_path)
        
        if size_mb > max_size_mb:
            large_files.append((file_path, size_mb))
            logger.warning(
                f"Arquivo grande detectado: {file_path.name} "
                f"({size_mb:.2f} MB > {max_size_mb} MB)"
            )
    
    return large_files


def validate_json_reports(
    reports_dir: Path,
    pattern: str = "*.json"
) -> List[Path]:
    """
    Valida integridade de arquivos JSON.
    
    Args:
        reports_dir: Diretório com relatórios
        pattern: Padrão de arquivos
        
    Returns:
        Lista de arquivos corrompidos
    """
    if not reports_dir.exists():
        return []
    
    corrupted_files = []
    
    for file_path in reports_dir.glob(pattern):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                json.load(f)
        except json.JSONDecodeError as e:
            corrupted_files.append(file_path)
            logger.error(
                f"JSON corrompido: {file_path.name} - {e}"
            )
        except Exception as e:
            logger.error(
                f"Erro ao validar {file_path.name}: {e}"
            )
    
    return corrupted_files


def run_maintenance() -> dict:
    """
    Executa rotina completa de manutenção.
    
    Returns:
        Dicionário com estatísticas da manutenção
    """
    logger.info("=== Iniciando manutenção do sistema ===")
    
    stats = {
        "simulation_reports_deleted": 0,
        "simulation_mb_freed": 0.0,
        "training_reports_deleted": 0,
        "training_mb_freed": 0.0,
        "large_files_found": 0,
        "corrupted_files_found": 0,
    }
    
    # Limpar relatórios de simulação
    sim_deleted, sim_mb = cleanup_old_reports(
        config.SIMULATION_REPORTS_DIR,
        keep_last=config.MAX_SIMULATION_REPORTS,
        max_age_days=config.REPORT_MAX_AGE_DAYS,
        pattern="*.json"
    )
    stats["simulation_reports_deleted"] = sim_deleted
    stats["simulation_mb_freed"] = sim_mb
    
    # Limpar relatórios de treinamento
    train_deleted, train_mb = cleanup_old_reports(
        config.REPORTS_DIR,
        keep_last=config.MAX_TRAINING_REPORTS,
        max_age_days=config.REPORT_MAX_AGE_DAYS,
        pattern="training_report_*.json"
    )
    stats["training_reports_deleted"] = train_deleted
    stats["training_mb_freed"] = train_mb
    
    # Checar arquivos grandes
    large_sim = check_large_reports(
        config.SIMULATION_REPORTS_DIR,
        max_size_mb=config.MAX_REPORT_SIZE_MB
    )
    large_train = check_large_reports(
        config.REPORTS_DIR,
        max_size_mb=config.MAX_REPORT_SIZE_MB
    )
    stats["large_files_found"] = len(large_sim) + len(large_train)
    
    # Validar JSONs
    corrupted_sim = validate_json_reports(config.SIMULATION_REPORTS_DIR)
    corrupted_train = validate_json_reports(config.REPORTS_DIR)
    stats["corrupted_files_found"] = len(corrupted_sim) + len(corrupted_train)
    
    # Limpar arquivos corrompidos
    for corrupted in corrupted_sim + corrupted_train:
        try:
            corrupted.unlink()
            logger.info(f"Removido arquivo corrompido: {corrupted.name}")
        except Exception as e:
            logger.error(f"Erro ao remover {corrupted}: {e}")
    
    total_mb = stats["simulation_mb_freed"] + stats["training_mb_freed"]
    total_deleted = stats["simulation_reports_deleted"] + stats["training_reports_deleted"]
    
    logger.info(
        f"=== Manutenção concluída: "
        f"{total_deleted} arquivos deletados, "
        f"{total_mb:.2f} MB liberados ==="
    )
    
    return stats


def get_disk_usage_summary() -> dict:
    """
    Retorna resumo de uso de disco.
    
    Returns:
        Dicionário com estatísticas de uso
    """
    def dir_size(directory: Path) -> float:
        """Calcula tamanho total de um diretório em MB."""
        if not directory.exists():
            return 0.0
        total = sum(f.stat().st_size for f in directory.rglob('*') if f.is_file())
        return total / (1024 * 1024)
    
    return {
        "simulation_reports_mb": dir_size(config.SIMULATION_REPORTS_DIR),
        "training_reports_mb": dir_size(config.REPORTS_DIR),
        "logs_mb": dir_size(config.LOG_DIR),
        "database_mb": get_file_size_mb(config.DB_PATH),
    }


# ============================================================================
# SCRIPT DE LINHA DE COMANDO
# ============================================================================

if __name__ == "__main__":
    # Configurar logging para execução standalone
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Executar manutenção
    print("\n" + "="*60)
    print("ROTINA DE MANUTENÇÃO DO SISTEMA DE TRADING")
    print("="*60 + "\n")
    
    # Uso de disco antes
    print("📊 Uso de disco ANTES da manutenção:")
    before = get_disk_usage_summary()
    for key, value in before.items():
        print(f"  • {key}: {value:.2f} MB")
    
    print("\n🧹 Executando limpeza...\n")
    
    # Executar manutenção
    stats = run_maintenance()
    
    # Uso de disco depois
    print("\n📊 Uso de disco APÓS manutenção:")
    after = get_disk_usage_summary()
    for key, value in after.items():
        print(f"  • {key}: {value:.2f} MB")
    
    # Resumo
    print("\n✅ Resumo:")
    print(f"  • Arquivos deletados: {stats['simulation_reports_deleted'] + stats['training_reports_deleted']}")
    print(f"  • Espaço liberado: {stats['simulation_mb_freed'] + stats['training_mb_freed']:.2f} MB")
    print(f"  • Arquivos grandes encontrados: {stats['large_files_found']}")
    print(f"  • Arquivos corrompidos removidos: {stats['corrupted_files_found']}")
    
    print("\n" + "="*60 + "\n")
