#!/bin/bash
# verify_auth.sh — Verifica presença do X-Custom-Auth nos pacotes capturados
# PPGCC/UFPI 2026-1 | Matrícula: 20261005083

IFACE="eth0"
SERVER_IP="172.20.0.10"
PORT_TCP=5001
PORT_RUDP=5002
EXPECTED_AUTH="20261005083:Luiz Nelson dos Santos Lima"

echo "=============================================="
echo " Verificação do X-Custom-Auth no tráfego TCP"
echo "=============================================="
echo " Aguardando pacotes na interface $IFACE..."
echo " (Execute o cliente TCP em outro terminal)"
echo ""

# Captura em tempo real e filtra pelo campo X-Custom-Auth
# -A: imprime payload em ASCII
# -s 0: captura pacote completo
# -l: line-buffered para saída imediata
tcpdump -i "$IFACE" -A -s 0 -l "host $SERVER_IP and port $PORT_TCP" 2>/dev/null \
    | grep --line-buffered -A2 "X-Custom-Auth" \
    | tee /data/logs/auth_verification.txt

echo ""
echo "Verificando nos PCAPs já capturados..."
for pcap in /data/pcap/scenario_*_tcp.pcap; do
    [ -f "$pcap" ] || continue
    echo ""
    echo ">>> $pcap"
    tcpdump -r "$pcap" -A -s 0 2>/dev/null | grep "X-Custom-Auth" | head -5
done

echo ""
echo "Verificação concluída. Log salvo em /data/logs/auth_verification.txt"
