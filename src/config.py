# config.py — Configurações globais do projeto
# PPGCC/UFPI — Projeto de Redes de Computadores 2026-1

MATRICULA = "20261005083"
NOME      = "Luiz Nelson dos Santos Lima"
X_CUSTOM_AUTH = f"{MATRICULA}:{NOME}"

# Rede
SERVER_HOST = "0.0.0.0"
SERVER_PORT_TCP  = 5001
SERVER_PORT_RUDP = 5002

# R-UDP — Selective Repeat
CHUNK_SIZE      = 1024        # bytes por pacote de dados
WINDOW_SIZE     = 16          # tamanho máximo da janela SR
TIMEOUT_SEC     = 0.5         # timeout por pacote (segundos)
MAX_RETRIES     = 20          # tentativas máximas por pacote

# Arquivo de teste
TEST_FILE_PATH  = "/tmp/testfile.bin"
TEST_FILE_SIZE  = 10 * 1024 * 1024   # 10 MB

# Logs
LOG_DIR  = "/data/logs"
PCAP_DIR = "/data/pcap"
CSV_DIR  = "/data/csv"
