#!/bin/bash
# run_all.sh — Pipeline completo: build → testes → análise
# PPGCC/UFPI — Projeto de Redes de Computadores 2026-1
#
# Uso: ./run_all.sh [tcp|rudp|both] [filesize_mb] [repetitions]
#   Exemplo: ./run_all.sh both 10 5

set -euo pipefail

MODE=${1:-both}
FILESIZE_MB=${2:-10}
REPS=${3:-5}

# Garante execução a partir da raiz do projeto
if [ ! -f "docker/docker-compose.yml" ]; then
    echo "[ERRO] Execute este script a partir da raiz do projeto."
    echo "       cd redes-ppgcc-fase1 && ./run_all.sh"
    exit 1
fi

echo "=============================================="
echo " PPGCC/UFPI — Pipeline Completo"
echo " Modo: $MODE | Arquivo: ${FILESIZE_MB}MB | Repetições: $REPS"
echo "=============================================="

# ─────────────────────────────────────────────
#  1. Build e subida dos containers
# ─────────────────────────────────────────────
echo ""
echo "[1/4] Build e subida dos containers..."
docker compose -f docker/docker-compose.yml down 2>/dev/null || true
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d

echo "[1/4] Aguardando servidor inicializar..."
sleep 5
docker compose -f docker/docker-compose.yml ps

# ─────────────────────────────────────────────
#  2. Executar testes dentro do container
# ─────────────────────────────────────────────
echo ""
echo "[2/4] Executando testes..."
docker exec ppgcc_client bash -c "
    chmod +x /scripts/run_tests.sh
    /scripts/run_tests.sh $MODE $FILESIZE_MB $REPS
"

# ─────────────────────────────────────────────
#  3. Copiar dados do container
# ─────────────────────────────────────────────
echo ""
echo "[3/4] Copiando dados do container..."
docker cp ppgcc_client:/data .
echo "[3/4] Dados copiados para data/"

# ─────────────────────────────────────────────
#  4. Instalar dependências e gerar gráficos
# ─────────────────────────────────────────────
echo ""
echo "[4/4] Verificando dependências Python..."

if ! python3 -c "import plotly, seaborn, pandas, numpy, matplotlib, kaleido" 2>/dev/null; then
    if ! command -v pip3 &>/dev/null; then
        echo "[4/4] Instalando pip3..."
        sudo apt-get install -y python3-pip
    fi
    pip3 install plotly seaborn pandas numpy matplotlib kaleido --break-system-packages
fi

echo "[4/4] Gerando gráficos..."
LOG_DIR=data/logs CSV_DIR=data/csv PLOTS_DIR=data/plots python3 analysis/analysis.py

echo ""
echo "=============================================="
echo " Pipeline concluído!"
echo " Gráficos : data/plots/"
echo " Logs     : data/logs/"
echo " PCAP     : data/pcap/"
echo " CSV      : data/csv/"
echo "=============================================="
