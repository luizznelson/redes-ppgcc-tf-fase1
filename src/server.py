#!/usr/bin/env python3
"""
server.py — Servidor TCP / R-UDP (Selective Repeat)
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
    SERVER_HOST, SERVER_PORT_TCP, SERVER_PORT_RUDP,
    CHUNK_SIZE, WINDOW_SIZE, TIMEOUT_SEC, MAX_RETRIES,
    X_CUSTOM_AUTH, LOG_DIR
)

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(LOG_DIR, "server.log"))
    ]
)
log = logging.getLogger("server")

# ─────────────────────────────────────────────
#  Protocolo R-UDP — formato do pacote
#  | seq (4B) | flags (1B) | checksum (16B) | payload |
#  flags: 0x01 = DATA, 0x02 = ACK, 0x04 = FIN, 0x08 = NACK
# ─────────────────────────────────────────────
HEADER_FMT  = "!I B 16s"
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 21 bytes

FLAG_DATA = 0x01
FLAG_ACK  = 0x02
FLAG_FIN  = 0x04
FLAG_NACK = 0x08


def build_packet(seq: int, flags: int, payload: bytes = b"") -> bytes:
    checksum = hashlib.md5(payload).digest()
    header   = struct.pack(HEADER_FMT, seq, flags, checksum)
    return header + payload


def parse_packet(raw: bytes):
    if len(raw) < HEADER_SIZE:
        return None, None, None, False
    seq, flags, checksum = struct.unpack(HEADER_FMT, raw[:HEADER_SIZE])
    payload  = raw[HEADER_SIZE:]
    valid    = hashlib.md5(payload).digest() == checksum
    return seq, flags, payload, valid


def send_ack(sock, addr, seq: int, ok: bool):
    flag = FLAG_ACK if ok else FLAG_NACK
    pkt  = build_packet(seq, flag)
    sock.sendto(pkt, addr)


# ─────────────────────────────────────────────
#  TCP Server
# ─────────────────────────────────────────────
class TCPServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((SERVER_HOST, SERVER_PORT_TCP))
        self.sock.listen(5)
        log.info(f"TCP server listening on {SERVER_HOST}:{SERVER_PORT_TCP}")

    def handle_client(self, conn, addr):
        log.info(f"[TCP] Connection from {addr}")
        start_time = None
        total_bytes = 0
        output_path = None
        try:
            # Recebe header: X-Custom-Auth + filename + filesize
            meta_raw = conn.recv(4096).decode()
            meta = json.loads(meta_raw)
            auth = meta.get("X-Custom-Auth", "")
            filename = meta.get("filename", "received_tcp.bin")
            filesize = int(meta.get("filesize", 0))
            log.info(f"[TCP] Auth: {auth} | File: {filename} | Size: {filesize}")

            # ACK do header
            conn.sendall(b"OK")

            output_path = f"/tmp/recv_tcp_{filename}"
            start_time  = time.perf_counter()

            with open(output_path, "wb") as f:
                while total_bytes < filesize:
                    chunk = conn.recv(min(CHUNK_SIZE * 4, filesize - total_bytes))
                    if not chunk:
                        break
                    f.write(chunk)
                    total_bytes += len(chunk)

            elapsed    = time.perf_counter() - start_time
            throughput = (total_bytes * 8) / elapsed / 1e6  # Mbps

            result = {
                "protocol": "TCP",
                "bytes_received": total_bytes,
                "elapsed_sec": round(elapsed, 4),
                "throughput_mbps": round(throughput, 4),
                "auth": auth
            }
            log.info(f"[TCP] Done: {result}")
            conn.sendall(json.dumps(result).encode())

            # Salva métrica
            self._save_metric(result)

        except Exception as e:
            log.error(f"[TCP] Error: {e}")
        finally:
            conn.close()

    def _save_metric(self, data: dict):
        path = os.path.join(LOG_DIR, "tcp_metrics.jsonl")
        with open(path, "a") as f:
            f.write(json.dumps(data) + "\n")

    def run(self):
        while True:
            conn, addr = self.sock.accept()
            t = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
            t.start()


# ─────────────────────────────────────────────
#  R-UDP Server — Selective Repeat
# ─────────────────────────────────────────────
class RUDPServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((SERVER_HOST, SERVER_PORT_RUDP))
        log.info(f"R-UDP server listening on {SERVER_HOST}:{SERVER_PORT_RUDP}")

    def _save_metric(self, data: dict):
        path = os.path.join(LOG_DIR, "rudp_metrics.jsonl")
        with open(path, "a") as f:
            f.write(json.dumps(data) + "\n")

    def receive_file(self, client_addr, meta: dict):
        """Selective Repeat receiver."""
        filename   = meta.get("filename", "received_rudp.bin")
        filesize   = int(meta.get("filesize", 0))
        auth       = meta.get("X-Custom-Auth", "")
        log.info(f"[R-UDP] Transfer from {client_addr} | Auth: {auth} | Size: {filesize}")

        buffer        = {}          # seq -> payload
        expected_next = 0
        total_bytes   = 0
        retransmissions = 0
        corrupt_pkts  = 0
        start_time    = time.perf_counter()
        output_path   = f"/tmp/recv_rudp_{filename}"

        self.sock.settimeout(TIMEOUT_SEC * 6)

        with open(output_path, "wb") as f:
            while True:
                try:
                    raw, addr = self.sock.recvfrom(HEADER_SIZE + CHUNK_SIZE + 64)
                except socket.timeout:
                    log.warning("[R-UDP] Receiver timeout — assuming FIN lost")
                    break

                seq, flags, payload, valid = parse_packet(raw)
                if seq is None:
                    continue

                # FIN packet
                if flags & FLAG_FIN:
                    send_ack(self.sock, addr, seq, True)
                    log.info(f"[R-UDP] FIN received (seq={seq})")
                    break

                if not valid:
                    corrupt_pkts += 1
                    send_ack(self.sock, addr, seq, False)   # NACK
                    continue

                # Aceita pacotes dentro da janela
                if seq not in buffer:
                    buffer[seq] = payload

                send_ack(self.sock, addr, seq, True)

                # Flush de pacotes em ordem
                while expected_next in buffer:
                    data = buffer.pop(expected_next)
                    f.write(data)
                    total_bytes += len(data)
                    expected_next += 1

        elapsed    = time.perf_counter() - start_time
        throughput = (total_bytes * 8) / elapsed / 1e6 if elapsed > 0 else 0

        result = {
            "protocol": "R-UDP",
            "bytes_received": total_bytes,
            "elapsed_sec": round(elapsed, 4),
            "throughput_mbps": round(throughput, 4),
            "corrupt_packets": corrupt_pkts,
            "auth": auth
        }
        log.info(f"[R-UDP] Done: {result}")
        self._save_metric(result)
        return result

    def run(self):
        """Loop principal: recebe metadados, executa transferência de forma síncrona."""
        while True:
            try:
                raw, addr = self.sock.recvfrom(4096)
                # Primeiro pacote é sempre o metadado (seq=0, FLAG_DATA, JSON payload)
                seq, flags, payload, valid = parse_packet(raw)
                if seq == 0 and valid:
                    meta = json.loads(payload.decode())
                    send_ack(self.sock, addr, 0, True)
                    # Síncrono: evita race condition de dois recvfrom no mesmo socket
                    self.receive_file(addr, meta)
            except Exception as e:
                log.error(f"[R-UDP] Loop error: {e}")


# ─────────────────────────────────────────────
#  Entrypoint
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Servidor TCP/R-UDP")
    parser.add_argument("--mode", choices=["tcp", "rudp", "both"], default="both")
    args = parser.parse_args()

    servers = []
    if args.mode in ("tcp", "both"):
        tcp = TCPServer()
        t = threading.Thread(target=tcp.run, daemon=True)
        t.start()
        servers.append(t)

    if args.mode in ("rudp", "both"):
        rudp = RUDPServer()
        t = threading.Thread(target=rudp.run, daemon=True)
        t.start()
        servers.append(t)

    log.info("Servers running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down.")
