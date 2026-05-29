#!/usr/bin/env python3
"""
client.py — Cliente TCP / R-UDP (Selective Repeat)
PPGCC/UFPI — Projeto de Redes de Computadores 2026-1
Matrícula: 20261005083 | Luiz Nelson dos Santos Lima
"""

import socket
import struct
import hashlib
import threading
import time
import json
import os
import logging
import argparse
from config import (
    SERVER_PORT_TCP, SERVER_PORT_RUDP,
    CHUNK_SIZE, WINDOW_SIZE, TIMEOUT_SEC, MAX_RETRIES,
    X_CUSTOM_AUTH, LOG_DIR, TEST_FILE_PATH, TEST_FILE_SIZE
)

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(LOG_DIR, "client.log"))
    ]
)
log = logging.getLogger("client")

# ─────────────────────────────────────────────
#  Mesmo protocolo do server.py
# ─────────────────────────────────────────────
HEADER_FMT  = "!I B 16s"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
FLAG_DATA   = 0x01
FLAG_ACK    = 0x02
FLAG_FIN    = 0x04
FLAG_NACK   = 0x08


def build_packet(seq: int, flags: int, payload: bytes = b"") -> bytes:
    checksum = hashlib.md5(payload).digest()
    header   = struct.pack(HEADER_FMT, seq, flags, checksum)
    return header + payload


def parse_ack(raw: bytes):
    if len(raw) < HEADER_SIZE:
        return None, None
    seq, flags, _ = struct.unpack(HEADER_FMT, raw[:HEADER_SIZE])
    return seq, flags


def generate_test_file(path: str, size: int):
    if not os.path.exists(path):
        log.info(f"Gerando arquivo de teste: {path} ({size // 1024 // 1024} MB)")
        with open(path, "wb") as f:
            f.write(os.urandom(size))


def save_metric(data: dict, filename: str):
    path = os.path.join(LOG_DIR, filename)
    with open(path, "a") as f:
        f.write(json.dumps(data) + "\n")


# ─────────────────────────────────────────────
#  TCP Client
# ─────────────────────────────────────────────
def send_tcp(server_ip: str, filepath: str, scenario: str = "A") -> dict:
    filesize = os.path.getsize(filepath)
    filename = os.path.basename(filepath)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((server_ip, SERVER_PORT_TCP))

    # Envia metadados
    meta = json.dumps({
        "X-Custom-Auth": X_CUSTOM_AUTH,
        "filename": filename,
        "filesize": filesize,
        "scenario": scenario
    }).encode()
    sock.sendall(meta)

    # Aguarda ACK do header
    ack = sock.recv(8)
    if ack != b"OK":
        raise RuntimeError("Server não confirmou o header")

    # Transferência
    start = time.perf_counter()
    bytes_sent = 0

    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE * 4)
            if not chunk:
                break
            sock.sendall(chunk)
            bytes_sent += len(chunk)

    # Recebe resultado do servidor
    result_raw = sock.recv(4096)
    elapsed = time.perf_counter() - start
    sock.close()

    result = json.loads(result_raw.decode())
    result["scenario"] = scenario
    result["bytes_sent"] = bytes_sent
    result["client_elapsed_sec"] = round(elapsed, 4)
    result["client_throughput_mbps"] = round((bytes_sent * 8) / elapsed / 1e6, 4)

    log.info(f"[TCP] Scenario {scenario}: {result}")
    save_metric(result, "tcp_client_metrics.jsonl")
    return result


# ─────────────────────────────────────────────
#  R-UDP Client — Selective Repeat
# ─────────────────────────────────────────────
class SelectiveRepeatSender:
    """
    Implementa o sender do Selective Repeat:
    - Janela de tamanho WINDOW_SIZE
    - Retransmissão individual por timeout
    - Aceita NACK como sinal imediato de retransmissão
    """

    def __init__(self, sock, server_addr, window_size=WINDOW_SIZE, timeout=TIMEOUT_SEC):
        self.sock        = sock
        self.addr        = server_addr
        self.window_size = window_size
        self.timeout     = timeout

        # Estado da janela
        self.base          = 0      # seq mais antigo sem ACK
        self.next_seq      = 0      # próximo seq a enviar
        self.chunks        = {}     # seq -> bytes (todos os chunks)
        self.acked         = set()  # seqs confirmados
        self.timers        = {}     # seq -> deadline (float)
        self.retransmissions = 0
        self.lock          = threading.Lock()
        self.done          = False

    def load_file(self, filepath: str):
        """Divide o arquivo em chunks numerados."""
        with open(filepath, "rb") as f:
            seq = 1  # 0 reservado para metadado
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                self.chunks[seq] = chunk
                seq += 1
        self.total_packets = seq - 1
        log.info(f"[SR] {self.total_packets} pacotes a enviar")

    def _send_packet(self, seq: int):
        payload = self.chunks[seq]
        pkt     = build_packet(seq, FLAG_DATA, payload)
        self.sock.sendto(pkt, self.addr)
        self.timers[seq] = time.perf_counter() + self.timeout

    def _ack_receiver(self):
        """Thread que recebe ACKs/NACKs."""
        self.sock.settimeout(self.timeout / 2)
        while not self.done:
            try:
                raw, _ = self.sock.recvfrom(HEADER_SIZE + 64)
                seq, flags = parse_ack(raw)
                if seq is None:
                    continue
                with self.lock:
                    if flags & FLAG_ACK:
                        self.acked.add(seq)
                        if seq == self.base:
                            # Avança a base da janela
                            while self.base in self.acked:
                                self.base += 1
                    elif flags & FLAG_NACK:
                        # Retransmissão imediata
                        if seq in self.chunks:
                            self._send_packet(seq)
                            self.retransmissions += 1
            except socket.timeout:
                pass
            except Exception as e:
                if not self.done:
                    log.debug(f"[SR] ACK recv error: {e}")

    def send(self, filepath: str, server_ip: str, scenario: str = "A") -> dict:
        self.load_file(filepath)
        filesize = os.path.getsize(filepath)
        filename = os.path.basename(filepath)

        # Envia metadado (seq=0)
        meta_payload = json.dumps({
            "X-Custom-Auth": X_CUSTOM_AUTH,
            "filename": filename,
            "filesize": filesize,
            "scenario": scenario
        }).encode()
        meta_pkt = build_packet(0, FLAG_DATA, meta_payload)

        # Aguarda ACK do metadado
        for attempt in range(MAX_RETRIES):
            self.sock.sendto(meta_pkt, self.addr)
            try:
                self.sock.settimeout(TIMEOUT_SEC)
                raw, _ = self.sock.recvfrom(HEADER_SIZE + 64)
                seq, flags = parse_ack(raw)
                if seq == 0 and (flags & FLAG_ACK):
                    log.info("[SR] Metadado confirmado, iniciando transferência")
                    break
            except socket.timeout:
                log.warning(f"[SR] Timeout metadado (tentativa {attempt+1})")
        else:
            raise RuntimeError("[SR] Servidor não confirmou metadado")

        # Inicia thread receptora de ACKs
        self.base     = 1
        self.next_seq = 1
        ack_thread    = threading.Thread(target=self._ack_receiver, daemon=True)
        ack_thread.start()

        start = time.perf_counter()

        while True:
            with self.lock:
                # Envia novos pacotes dentro da janela
                while (self.next_seq <= self.total_packets and
                       self.next_seq < self.base + self.window_size):
                    self._send_packet(self.next_seq)
                    self.next_seq += 1

                # Retransmite pacotes com timeout expirado
                now = time.perf_counter()
                for seq in range(self.base, self.next_seq):
                    if seq not in self.acked and self.timers.get(seq, 0) < now:
                        self._send_packet(seq)
                        self.retransmissions += 1

                # Verifica se todos os pacotes foram confirmados
                if self.base > self.total_packets:
                    break

            time.sleep(0.001)

        # Envia FIN
        fin_pkt = build_packet(self.next_seq, FLAG_FIN)
        for _ in range(5):
            self.sock.sendto(fin_pkt, self.addr)
            time.sleep(0.05)

        self.done = True
        elapsed   = time.perf_counter() - start

        result = {
            "protocol": "R-UDP",
            "window_size": self.window_size,
            "total_packets": self.total_packets,
            "retransmissions": self.retransmissions,
            "bytes_sent": filesize,
            "elapsed_sec": round(elapsed, 4),
            "throughput_mbps": round((filesize * 8) / elapsed / 1e6, 4),
            "scenario": scenario
        }
        log.info(f"[SR] Scenario {scenario}: {result}")
        save_metric(result, "rudp_client_metrics.jsonl")
        return result


def send_rudp(server_ip: str, filepath: str, scenario: str = "A") -> dict:
    sock   = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server = (server_ip, SERVER_PORT_RUDP)
    sender = SelectiveRepeatSender(sock, server)
    result = sender.send(filepath, server_ip, scenario)
    sock.close()
    return result


# ─────────────────────────────────────────────
#  Entrypoint
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cliente TCP/R-UDP")
    parser.add_argument("--mode",     choices=["tcp", "rudp", "both"], default="both")
    parser.add_argument("--server",   default="server", help="IP/hostname do servidor")
    parser.add_argument("--file",     default=TEST_FILE_PATH)
    parser.add_argument("--filesize", type=int, default=TEST_FILE_SIZE)
    parser.add_argument("--scenario", default="A", help="Cenário de rede (A, B ou C)")
    args = parser.parse_args()

    generate_test_file(args.file, args.filesize)

    results = {}
    if args.mode in ("tcp", "both"):
        results["TCP"] = send_tcp(args.server, args.file, args.scenario)

    if args.mode in ("rudp", "both"):
        results["R-UDP"] = send_rudp(args.server, args.file, args.scenario)

    print("\n=== RESULTADOS ===")
    print(json.dumps(results, indent=2))
