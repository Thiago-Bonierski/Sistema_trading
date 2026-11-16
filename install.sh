#!/bin/bash
# Script de instalação automatizada do Sistema de Trading Refatorado
# Versão: 3.0 - Arquitetura Orientada a Estado Único

set -e

echo "=================================================="
echo "🚀 INSTALANDO SISTEMA DE TRADING - VERSÃO 3.0"
echo "=================================================="
echo ""

# 1. Verificar Python
echo "1. Verificando Python..."
if ! command -v python3 &> /dev/null; then
    echo "   ❌ Python 3 não encontrado. Por favor instale Python 3.8+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "   ✅ Python $PYTHON_VERSION encontrado"
echo ""

# 2. Criar ambiente virtual automaticamente
echo "2. Criando ambiente virtual..."
if [ -d "venv" ]; then
    echo "   ⏭️  Ambiente virtual já existe, reutilizando"
else
    python3 -m venv venv
    echo "   ✅ Ambiente virtual criado"
fi
# shellcheck disable=SC1091
source venv/bin/activate
echo "   ✅ Ambiente virtual ativado"
echo ""

# 3. Atualizar pip e instalar dependências
echo "3. Instalando dependências..."
pip install --upgrade pip > /dev/null 2>&1
if pip install -r requirements.txt; then
    echo "   ✅ Dependências instaladas com sucesso"
else
    echo "   ❌ Erro ao instalar dependências"
    exit 1
fi
echo ""

# 4. Criar diretórios necessários
echo "4. Criando diretórios..."
mkdir -p logs
mkdir -p reports
mkdir -p simulation_reports
echo "   ✅ Diretórios criados"
echo ""

# 5. Inicializar banco de dados (inclui tabelas de estado vivo)
echo "5. Inicializando banco de dados..."
if python3 -c "from database import init_database; init_database()"; then
    echo "   ✅ Banco de dados inicializado"
else
    echo "   ❌ Erro ao inicializar banco de dados"
    exit 1
fi
echo ""

# 6. Configurar .env automaticamente
echo "6. Configurando variáveis de ambiente..."
if [ -f .env ]; then
    echo "   ⏭️  Arquivo .env já existe, mantendo configuracoes atuais"
elif [ -f .env.example ]; then
    cp .env.example .env
    echo "   ✅ Arquivo .env criado a partir do .env.example"
else
    # Fallback: cria um .env mínimo para não quebrar o boot
    cat > .env <<'EOF'
TELEGRAM_TOKEN=
CHAT_ID=
FLASK_DEBUG=False
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
LOG_LEVEL=INFO
CONTROL_TOKEN=
EOF
    echo "   ✅ Arquivo .env criado (modelo mínimo)"
fi
echo "   ⚠️  Edite .env para configurar TELEGRAM_TOKEN, CHAT_ID e CONTROL_TOKEN"
echo ""

# 7. Verificar importações básicas
echo "7. Verificando importações básicas..."
if python3 -c "
import flask
import pandas
import numpy
import sklearn
import dotenv
print('   ✅ Todas as importações básicas OK')
"; then
    :
else
    echo "   ⚠️  Alguns módulos não carregaram corretamente"
fi
echo ""

# 8. Executar testes (não bloqueia a instalação)
echo "8. Executando testes automatizados..."
if python3 -m pytest tests/ -q; then
    echo "   ✅ Testes passaram"
else
    echo "   ⚠️  Alguns testes falharam (não crítico para instalação)"
fi
echo ""

# Finalização
echo "=================================================="
echo "✅ INSTALAÇÃO CONCLUÍDA COM SUCESSO!"
echo "=================================================="
echo ""
echo "Ambiente virtual: ./venv/bin/activate"
echo "Para ativar: source venv/bin/activate"
echo ""
echo "Próximos passos:"
echo "1. Edite o arquivo .env (TOKEN, CHAT_ID, CONTROL_TOKEN)"
echo "2. Inicie o sistema: python app.py"
echo "3. Acesse: http://127.0.0.1:5000"
echo ""
echo "Documentação: README.md"
echo "=================================================="
echo ""