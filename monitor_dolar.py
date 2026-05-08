"""
Cliente para APIs de cotação e notificações.

Funções:
- pegar_cotacao(): Busca cotações da API AwesomeAPI
- enviar_mensagem(): Envia notificações via Telegram

Configuração via variáveis de ambiente (.env):
- TELEGRAM_TOKEN: Token do bot Telegram
- CHAT_ID: ID do chat para notificações
"""
import os
from typing import Optional, Dict, Any
from datetime import datetime
import logging
import time

import requests
from dotenv import load_dotenv

from logging_config import setup_logging

_api_block_until = 0
_last_quotes = {}

# Carregar variáveis de ambiente
load_dotenv()

# Configurar logging
logger = setup_logging("monitor_dolar", "INFO")

# Configurações do Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")

# Configurações da API
API_BASE_URL = "https://economia.awesomeapi.com.br"
API_TIMEOUT = 10  # segundos
USER_AGENT = "Mozilla/5.0 (TradingBot/2.0)"


def enviar_mensagem(texto: str) -> Optional[Dict[str, Any]]:
    """
    Envia mensagem via Telegram bot.
    
    Requer variáveis de ambiente:
    - TELEGRAM_TOKEN
    - CHAT_ID
    
    Args:
        texto: Mensagem a enviar
        
    Returns:
        Resposta da API do Telegram ou None se erro
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            "Telegram não configurado: TOKEN ou CHAT_ID ausentes no .env"
        )
        return None
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto
    }
    
    try:
        response = requests.post(url, data=payload, timeout=API_TIMEOUT)
        response.raise_for_status()
        
        result = response.json()
        
        logger.debug(f"Mensagem Telegram enviada: {texto[:50]}...")
        return result
        
    except requests.exceptions.Timeout:
        logger.error("Timeout ao enviar mensagem para Telegram")
        return None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao enviar mensagem para Telegram: {e}")
        return None
        
    except Exception as e:
        logger.error(
            f"Erro inesperado ao enviar mensagem: {e}",
            exc_info=True
        )
        return None



def pegar_cotacao(par: str = "USD-BRL"):
    global _api_block_until

    now = time.time()

    # Se a API está em cooldown, não insiste
    if now < _api_block_until:
        logger.warning(
            f"API em cooldown por rate limit. Ignorando {par} temporariamente."
        )
        return _last_quotes.get(par)

    url = f"{API_BASE_URL}/last/{par}"

    try:
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(url, headers=headers, timeout=API_TIMEOUT)

        if response.status_code == 429:
            logger.warning(
                f"Rate limit da API atingido para {par}. Pausando consultas por 5 minutos."
            )
            _api_block_until = time.time() + 300  # 5 minutos

            # Se existir última cotação válida, reutiliza
            return _last_quotes.get(par)

        if response.status_code != 200:
            logger.error(f"Erro na API: Status {response.status_code} para {par}")
            return _last_quotes.get(par)

        dados = response.json()
        chave = par.replace("-", "")

        if chave not in dados:
            logger.error(f"Par {par} não encontrado na resposta da API")
            return _last_quotes.get(par)

        cotacao_data = dados[chave]
        preco = float(cotacao_data["bid"])
        timestamp = cotacao_data.get("timestamp", "")

        try:
            if timestamp:
                dt = datetime.fromtimestamp(int(timestamp))
                horario = dt.strftime("%H:%M:%S")
            else:
                horario = datetime.now().strftime("%H:%M:%S")
        except Exception:
            horario = datetime.now().strftime("%H:%M:%S")

        resultado = {
            "preco": preco,
            "horario": horario,
            "par": par,
            "timestamp": timestamp,
        }

        # Salva última cotação válida
        _last_quotes[par] = resultado

        return resultado

    except requests.exceptions.Timeout:
        logger.error(f"Timeout ao buscar cotação de {par}")
        return _last_quotes.get(par)

    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao buscar cotação de {par}: {e}")
        return _last_quotes.get(par)

    except Exception as e:
        logger.error(f"Erro inesperado ao buscar {par}: {e}", exc_info=True)
        return _last_quotes.get(par)


def verificar_configuracao() -> bool:
    """
    Verifica se configurações estão corretas.
    
    Returns:
        True se configurado corretamente
    """
    issues = []
    
    if not TELEGRAM_TOKEN:
        issues.append("TELEGRAM_TOKEN não definido em .env")
    
    if not TELEGRAM_CHAT_ID:
        issues.append("CHAT_ID não definido em .env")
    
    if issues:
        logger.warning("Problemas de configuração:")
        for issue in issues:
            logger.warning(f"  • {issue}")
        return False
    
    logger.info("✅ Configuração verificada: Telegram OK")
    return True


# ============================================================================
# SCRIPT DE TESTE
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 TESTANDO MÓDULO MONITOR_DOLAR")
    print("="*60 + "\n")
    
    # Verificar configuração
    print("1. Verificando configuração...")
    config_ok = verificar_configuracao()
    
    if not config_ok:
        print("   ⚠️  Telegram não configurado (opcional)")
        print("   Para habilitar: configure TELEGRAM_TOKEN e CHAT_ID no .env\n")
    else:
        print("   ✅ Telegram configurado\n")
    
    # Testar cotação USD
    print("2. Testando cotação USD-BRL...")
    cotacao_usd = pegar_cotacao("USD-BRL")
    
    if cotacao_usd:
        print(f"   ✅ USD: R$ {cotacao_usd['preco']:.2f} ({cotacao_usd['horario']})")
    else:
        print("   ❌ Erro ao obter cotação USD")
    
    # Testar cotação BTC
    print("\n3. Testando cotação BTC-BRL...")
    cotacao_btc = pegar_cotacao("BTC-BRL")

    if cotacao_btc:
        print(f"   ✅ BTC: R$ {cotacao_btc['preco']:,.2f} ({cotacao_btc['horario']})")
    else:
        print("   ❌ Erro ao obter cotação BTC")

    # Testar cotação ETH
    print("\n4. Testando cotação ETH-BRL...")
    cotacao_eth = pegar_cotacao("ETH-BRL")

    if cotacao_eth:
        print(f"   ✅ ETH: R$ {cotacao_eth['preco']:,.2f} ({cotacao_eth['horario']})")
    else:
        print("   ❌ Erro ao obter cotação ETH")

    # Testar cotação SOL
    print("\n5. Testando cotação SOL-BRL...")
    cotacao_sol = pegar_cotacao("SOL-BRL")

    if cotacao_sol:
        print(f"   ✅ SOL: R$ {cotacao_sol['preco']:,.2f} ({cotacao_sol['horario']})")
    else:
        print("   ❌ Erro ao obter cotação SOL")

    # Testar mensagem Telegram (se configurado)
    if config_ok and cotacao_usd:
        print("\n4. Testando envio de mensagem Telegram...")
        mensagem = (
            f"🤖 Monitor de Dólar - Teste\n"
            f"USD: R$ {cotacao_usd['preco']:.2f}\n"
            f"Horário: {cotacao_usd['horario']}"
        )
        
        resultado = enviar_mensagem(mensagem)
        
        if resultado:
            print("   ✅ Mensagem enviada com sucesso")
        else:
            print("   ❌ Erro ao enviar mensagem")
    
    print("\n" + "="*60)
    print("TESTES CONCLUÍDOS")
    print("="*60 + "\n")
