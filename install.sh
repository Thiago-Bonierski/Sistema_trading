#!/bin/bash
# Script de instalação do Sistema de Trading Refatorado

echo "=================================================="
echo "🚀 INSTALANDO SISTEMA DE TRADING - VERSÃO 2.0"
echo "=================================================="
echo ""

# Verificar Python
echo "1. Verificando Python..."
if ! command -v python3 &> /dev/null; then
    echo "   ❌ Python 3 não encontrado. Por favor instale Python 3.8+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "   ✅ Python $PYTHON_VERSION encontrado"
echo ""

# Criar ambiente virtual (opcional mas recomendado)
echo "2. Deseja criar um ambiente virtual? (recomendado) [s/N]"
read -r criar_venv

if [[ $criar_venv == "s" || $criar_venv == "S" ]]; then
    echo "   Criando ambiente virtual..."
    python3 -m venv venv
    source venv/bin/activate
    echo "   ✅ Ambiente virtual criado e ativado"
else
    echo "   ⏭️  Pulando criação de ambiente virtual"
fi
echo ""

# Instalar dependências
echo "3. Instalando dependências..."
    pip install --upgrade pip
    pip install -r requirements.txt

if [ $? -eq 0 ]; then
    echo "   ✅ Dependências instaladas com sucesso"
else
    echo "   ❌ Erro ao instalar dependências"
    exit 1
fi
echo ""

# Criar diretórios necessários
echo "4. Criando diretórios..."
mkdir -p logs
mkdir -p reports
mkdir -p simulation_reports
mkdir -p tests/__pycache__
echo "   ✅ Diretórios criados"
echo ""

# Inicializar banco de dados
echo "5. Inicializando banco de dados..."
python3 -c "from database import init_database; init_database()"

if [ $? -eq 0 ]; then
    echo "   ✅ Banco de dados inicializado"
else
    echo "   ❌ Erro ao inicializar banco de dados"
    exit 1
fi
echo ""

# Configurar .env
echo "6. Configurando variáveis de ambiente..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "   ✅ Arquivo .env criado"
    echo "   ⚠️  Edite .env para adicionar TELEGRAM_TOKEN e CHAT_ID se necessário"
else
    echo "   ⏭️  Arquivo .env já existe"
fi
echo ""

# Executar testes
echo "7. Deseja executar os testes automatizados? [s/N]"
read -r executar_testes

if [[ $executar_testes == "s" || $executar_testes == "S" ]]; then
    echo "   Executando testes..."
    pytest tests/ -v
    
    if [ $? -eq 0 ]; then
        echo "   ✅ Todos os testes passaram"
    else
        echo "   ⚠️  Alguns testes falharam (não crítico)"
    fi
else
    echo "   ⏭️  Pulando testes"
fi
echo ""

# Limpeza inicial
echo "8. Limpando arquivos antigos..."
python3 utils/maintenance.py
echo ""

# Finalização
echo "=================================================="
echo "✅ INSTALAÇÃO CONCLUÍDA COM SUCESSO!"
echo "=================================================="
echo ""
echo "📚 Próximos passos:"
echo ""
echo "1. Revisar configurações em config.py"
echo "2. (Opcional) Configurar Telegram no .env"
echo "3. Executar demonstração: python demo.py"
echo "4. Iniciar sistema: python app.py"
echo ""
echo "Documentação completa em README.md"
echo "=================================================="
echo ""
