#!/usr/bin/env python3
"""
pcap_to_csv.py — Converte arquivo .pcap para CSV
PPGCC/UFPI — Projeto de Redes de Computadores 2026-1
Matrícula: 20261005083 | Luiz Nelson dos Santos Lima

Uso: python3 pcap_to_csv.py <input.pcap> <output.csv>

Campos exportados:
  timestamp, src_ip, dst_ip, protocol, src_port, dst_port,
  length, tcp_flags, tcp_seq, tcp_ack, payload_size
"""

import sys
import csv
import os

def convert(pcap_path: str, csv_path: str):
    try:
        from scapy.all import rdpcap, IP, TCP, UDP
    except ImportError:
        print("[ERROR] Scapy não encontrado. Instale com: pip3 install scapy")
        sys.exit(1)

    if not os.path.exists(pcap_path):
        print(f"[ERROR] Arquivo não encontrado: {pcap_path}")
        sys.exit(1)

    print(f"[pcap_to_csv] Lendo {pcap_path} ...")
    packets = rdpcap(pcap_path)
    print(f"[pcap_to_csv] {len(packets)} pacotes encontrados")

    fields = [
        "timestamp", "src_ip", "dst_ip", "protocol",
        "src_port", "dst_port", "length",
        "tcp_flags", "tcp_seq", "tcp_ack", "payload_size"
    ]

    rows = []
    for pkt in packets:
        if not pkt.haslayer(IP):
            continue

        ip   = pkt[IP]
        row  = {
            "timestamp":    float(pkt.time),
            "src_ip":       ip.src,
            "dst_ip":       ip.dst,
            "protocol":     "TCP" if pkt.haslayer(TCP) else ("UDP" if pkt.haslayer(UDP) else "OTHER"),
            "src_port":     "",
            "dst_port":     "",
            "length":       len(pkt),
            "tcp_flags":    "",
            "tcp_seq":      "",
            "tcp_ack":      "",
            "payload_size": 0,
        }

        if pkt.haslayer(TCP):
            tcp = pkt[TCP]
            row["src_port"]     = tcp.sport
            row["dst_port"]     = tcp.dport
            row["tcp_flags"]    = str(tcp.flags)
            row["tcp_seq"]      = tcp.seq
            row["tcp_ack"]      = tcp.ack
            row["payload_size"] = len(tcp.payload)

        elif pkt.haslayer(UDP):
            from scapy.all import UDP as _UDP
            udp = pkt[_UDP]
            row["src_port"]     = udp.sport
            row["dst_port"]     = udp.dport
            row["payload_size"] = len(udp.payload)

        rows.append(row)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[pcap_to_csv] {len(rows)} linhas escritas em {csv_path}")

    # Estatísticas básicas
    tcp_count  = sum(1 for r in rows if r["protocol"] == "TCP")
    udp_count  = sum(1 for r in rows if r["protocol"] == "UDP")
    total_size = sum(r["length"] for r in rows)
    print(f"[pcap_to_csv] TCP={tcp_count} | UDP={udp_count} | Total bytes={total_size:,}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Uso: python3 {sys.argv[0]} <input.pcap> <output.csv>")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
