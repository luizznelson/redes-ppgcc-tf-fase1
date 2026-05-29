#!/bin/bash
# run_tests.sh — Executa os 3 cenários de rede (A, B, C) com coleta tcpdump
# PPGCC/UFPI — Projeto de Redes de Computadores 2026-1
# Matrícula: 20261005083 | Luiz Nelson dos Santos Lima
#
# Uso: ./run_tests.sh [tcp|rudp|both] [filesize_mb] [repetitions]
#   Exemplo: ./run_tests.sh both 10 3

set -euo pipefail

MODE=${1:-both}
FILESIZE_MB=${2:-10}
REPS=${3:-1}
FILESIZE_BYTES=$((FILESIZE_MB * 1024 * 1024))
SERVER_IP="172.20.0.10"
IFACE="eth0"
DATA_DIR="/data"
PCAP_DIR="$DATA_DIR/pcap"
CSV_DIR="$DATA_DIR/csv"
LOG_DIR="$DATA_DIR/logs"

mkdir -p "$PCAP_DIR" "$CSV_DIR" "$LOG_DIR"

echo "=============================================="
echo " PPGCC/UFPI — Testes de Transferência"
echo " Modo: $MODE | Arquivo: ${FILESIZE_MB}MB | Repetições: $REPS"
echo "=============================================="

# ─────────────────────────────────────────────
#  Função: aplica cenário de rede via tc
# ─────────────────────────────────────────────
apply_scenario() {
    local scenario=$1
    local loss=$2
    local delay=$3

    echo "[tc] Aplicando Cenário $scenario: loss=${loss}% delay=${delay}ms"

    # Remove regra anterior (ignora erro se não existir)
    tc qdisc del dev "$IFACE" root 2>/dev/null || true

    if [ "$loss" -eq 0 ]; then
        tc qdisc add dev "$IFACE" root netem delay "${delay}ms"
    else
        tc qdisc add dev "$IFACE" root netem \
            delay "${delay}ms" \
            loss "${loss}%"
    fi

    echo "[tc] Cenário $scenario aplicado:"
    tc qdisc show dev "$IFACE"
}

# ─────────────────────────────────────────────
#  Função: inicia tcpdump em background
# ─────────────────────────────────────────────
start_tcpdump() {
    local scenario=$1
    local protocol=$2
    local rep=$3
    local pcap_file="$PCAP_DIR/scenario_${scenario}_${protocol}_rep${rep}.pcap"

    # Mata tcpdump anterior se existir
    pkill -f tcpdump 2>/dev/null || true
    sleep 0.5

    tcpdump -i "$IFACE" -w "$pcap_file" \
        -s 0 \
        "host $SERVER_IP" &
    TCPDUMP_PID=$!
    echo "[tcpdump] PID=$TCPDUMP_PID | Capturando em $pcap_file"
    sleep 1  # aguarda tcpdump inicializar
}

# ─────────────────────────────────────────────
#  Função: para tcpdump e exporta CSV
# ─────────────────────────────────────────────
stop_tcpdump() {
    local scenario=$1
    local protocol=$2
    local rep=$3
    local pcap_file="$PCAP_DIR/scenario_${scenario}_${protocol}_rep${rep}.pcap"
    local csv_file="$CSV_DIR/scenario_${scenario}_${protocol}_rep${rep}.csv"

    sleep 1
    kill "$TCPDUMP_PID" 2>/dev/null || true
    wait "$TCPDUMP_PID" 2>/dev/null || true
    echo "[tcpdump] Captura encerrada"

    # Converte pcap para CSV usando Python/Scapy
    python3 /scripts/pcap_to_csv.py "$pcap_file" "$csv_file"
    echo "[tcpdump] CSV exportado: $csv_file"
}

# ─────────────────────────────────────────────
#  Função: executa um teste completo
# ─────────────────────────────────────────────
run_test() {
    local scenario=$1
    local protocol=$2
    local rep=$3

    echo ""
    echo "--- Cenário $scenario | Protocolo: $protocol | Rep: $rep/$REPS ---"

    start_tcpdump "$scenario" "$protocol" "$rep"

    python3 /app/client.py \
        --mode "$protocol" \
        --server "$SERVER_IP" \
        --file "/tmp/testfile.bin" \
        --filesize "$FILESIZE_BYTES" \
        --scenario "$scenario"

    stop_tcpdump "$scenario" "$protocol" "$rep"
}

# ─────────────────────────────────────────────
#  Cenários de rede
# ─────────────────────────────────────────────
declare -A LOSS=(  [A]=0   [B]=10  [C]=20  )
declare -A DELAY=( [A]=10  [B]=50  [C]=100 )

for scenario in A B C; do
    apply_scenario "$scenario" "${LOSS[$scenario]}" "${DELAY[$scenario]}"
    sleep 1

    for rep in $(seq 1 "$REPS"); do
        if [ "$MODE" = "both" ]; then
            run_test "$scenario" "tcp" "$rep"
            sleep 2
            run_test "$scenario" "rudp" "$rep"
        else
            run_test "$scenario" "$MODE" "$rep"
        fi
        sleep 2
    done
done

# Remove tc ao finalizar
tc qdisc del dev "$IFACE" root 2>/dev/null || true
echo ""
echo "=============================================="
echo " Todos os testes concluídos!"
echo " Logs    : $LOG_DIR"
echo " PCAP    : $PCAP_DIR"
echo " CSV     : $CSV_DIR"
echo "=============================================="
