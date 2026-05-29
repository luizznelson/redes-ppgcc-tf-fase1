#!/usr/bin/env python3
"""
analysis.py — Análise estatística e geração de gráficos (Fase 1)
PPGCC/UFPI — Projeto de Redes de Computadores 2026-1
Matrícula: 20261005083 | Luiz Nelson dos Santos Lima

Gera:
  1. Throughput TCP vs R-UDP por cenário (barras com desvio padrão)
  2. Latência / tempo de transferência por cenário
  3. Retransmissões R-UDP por cenário
  4. Validação cruzada: Aplicação vs TCPDump (volume de dados)
  5. Heatmap de comparação de métricas

Salva gráficos em /data/plots/ (PNG + HTML interativo Plotly)
"""

import os
import json
import glob
import csv
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ─────────────────────────────────────────────
#  Configuração
# ─────────────────────────────────────────────
LOG_DIR   = os.environ.get("LOG_DIR",   "/data/logs")
CSV_DIR   = os.environ.get("CSV_DIR",   "/data/csv")
PLOTS_DIR = os.environ.get("PLOTS_DIR", "/data/plots")
os.makedirs(PLOTS_DIR, exist_ok=True)

SCENARIOS = ["A", "B", "C"]
SCENARIO_LABELS = {
    "A": "A (0% loss / 10ms)",
    "B": "B (10% loss / 50ms)",
    "C": "C (20% loss / 100ms)",
}
COLORS = {"TCP": "#2196F3", "R-UDP": "#FF5722"}

# ─────────────────────────────────────────────
#  Carregamento de métricas
# ─────────────────────────────────────────────
def load_jsonl(path: str) -> list[dict]:
    records = []
    if not os.path.exists(path):
        return records
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def load_app_metrics() -> pd.DataFrame:
    tcp_records  = load_jsonl(os.path.join(LOG_DIR, "tcp_client_metrics.jsonl"))
    rudp_records = load_jsonl(os.path.join(LOG_DIR, "rudp_client_metrics.jsonl"))
    all_records  = tcp_records + rudp_records
    if not all_records:
        print("[WARN] Nenhuma métrica de aplicação encontrada. Usando dados sintéticos para demonstração.")
        return generate_synthetic_data()
    df = pd.DataFrame(all_records)
    df["scenario_label"] = df["scenario"].map(SCENARIO_LABELS)
    return df


def generate_synthetic_data() -> pd.DataFrame:
    """
    Gera dados sintéticos realistas para demonstração quando os experimentos
    ainda não foram executados. Substitua pelos dados reais após rodar run_tests.sh.
    """
    np.random.seed(42)
    rows = []
    configs = {
        "A": {"tcp_tp": 85, "rudp_tp": 72, "tcp_ret": 0,  "rudp_ret": 2},
        "B": {"tcp_tp": 42, "rudp_tp": 38, "tcp_ret": 12, "rudp_ret": 45},
        "C": {"tcp_tp": 18, "rudp_tp": 21, "tcp_ret": 35, "rudp_ret": 130},
    }
    for sc, cfg in configs.items():
        for run in range(5):
            noise = np.random.normal(0, 0.05)
            rows.append({
                "protocol": "TCP", "scenario": sc,
                "throughput_mbps": max(0.1, cfg["tcp_tp"] * (1 + noise)),
                "elapsed_sec": 10 / max(0.1, cfg["tcp_tp"] * (1 + noise)),
                "retransmissions": 0,
                "bytes_sent": 10 * 1024 * 1024,
                "scenario_label": SCENARIO_LABELS[sc]
            })
            rows.append({
                "protocol": "R-UDP", "scenario": sc,
                "throughput_mbps": max(0.1, cfg["rudp_tp"] * (1 + np.random.normal(0, 0.08))),
                "elapsed_sec": 10 / max(0.1, cfg["rudp_tp"] * (1 + noise)),
                "retransmissions": max(0, int(cfg["rudp_ret"] * (1 + np.random.normal(0, 0.2)))),
                "bytes_sent": 10 * 1024 * 1024,
                "scenario_label": SCENARIO_LABELS[sc]
            })
    return pd.DataFrame(rows)


def load_tcpdump_metrics() -> pd.DataFrame:
    """Lê os CSVs gerados pelo pcap_to_csv.py e agrega por cenário/protocolo/repetição."""
    rows = []
    for sc in SCENARIOS:
        for proto in ["tcp", "rudp"]:
            # Suporta tanto o padrão antigo (sem _repN) quanto o novo (com _repN)
            pattern_new = os.path.join(CSV_DIR, f"scenario_{sc}_{proto}_rep*.csv")
            pattern_old = os.path.join(CSV_DIR, f"scenario_{sc}_{proto}.csv")
            csv_files = sorted(glob.glob(pattern_new)) or glob.glob(pattern_old)
            for csv_path in csv_files:
                df = pd.read_csv(csv_path)
                if df.empty:
                    continue
                total_bytes = df["length"].sum()
                pkt_count   = len(df)
                duration    = df["timestamp"].max() - df["timestamp"].min() if len(df) > 1 else 0
                throughput  = (total_bytes * 8) / duration / 1e6 if duration > 0 else 0
                rows.append({
                    "scenario": sc,
                    "protocol": proto.upper().replace("RUDP", "R-UDP"),
                    "tcpdump_bytes": int(total_bytes),
                    "tcpdump_pkts":  int(pkt_count),
                    "tcpdump_duration_sec": round(duration, 4),
                    "tcpdump_throughput_mbps": round(throughput, 4),
                })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
#  Gráficos
# ─────────────────────────────────────────────
def plot_throughput(df: pd.DataFrame):
    """Gráfico 1: Throughput médio ± desvio padrão — TCP vs R-UDP por cenário."""
    stats = df.groupby(["scenario", "protocol"])["throughput_mbps"].agg(["mean", "std"]).reset_index()
    stats.columns = ["scenario", "protocol", "mean", "std"]
    stats["scenario_label"] = stats["scenario"].map(SCENARIO_LABELS)

    # Plotly
    fig = go.Figure()
    for proto, color in COLORS.items():
        sub = stats[stats["protocol"] == proto]
        fig.add_trace(go.Bar(
            name=proto,
            x=sub["scenario_label"],
            y=sub["mean"],
            error_y=dict(type="data", array=sub["std"].fillna(0).tolist(), visible=True),
            marker_color=color,
            width=0.35,
        ))
    fig.update_layout(
        title="Throughput Médio por Cenário — TCP vs R-UDP",
        xaxis_title="Cenário de Rede",
        yaxis_title="Throughput (Mbps)",
        barmode="group",
        template="plotly_white",
        legend_title="Protocolo",
        font=dict(size=13),
    )
    fig.write_html(os.path.join(PLOTS_DIR, "throughput.html"))
    fig.write_image(os.path.join(PLOTS_DIR, "throughput.png"), width=900, height=500)

    # Seaborn (para relatório)
    fig2, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(SCENARIOS))
    width = 0.35
    for i, (proto, color) in enumerate(COLORS.items()):
        sub = stats[stats["protocol"] == proto].sort_values("scenario")
        offset = (i - 0.5) * width
        bars = ax.bar(x + offset, sub["mean"], width, label=proto,
                      color=color, alpha=0.85,
                      yerr=sub["std"].fillna(0), capsize=5)
    ax.set_xticks(x)
    ax.set_xticklabels([SCENARIO_LABELS[s] for s in SCENARIOS], rotation=15)
    ax.set_xlabel("Cenário de Rede")
    ax.set_ylabel("Throughput (Mbps)")
    ax.set_title("Throughput Médio — TCP vs R-UDP")
    ax.legend(title="Protocolo")
    ax.grid(axis="y", alpha=0.4)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "throughput_seaborn.png"), dpi=150)
    plt.close()
    print("[OK] Gráfico: throughput")


def plot_latency(df: pd.DataFrame):
    """Gráfico 2: Tempo de transferência por cenário."""
    fig = px.box(
        df, x="scenario_label", y="elapsed_sec",
        color="protocol", color_discrete_map=COLORS,
        title="Tempo de Transferência por Cenário — TCP vs R-UDP",
        labels={"scenario_label": "Cenário", "elapsed_sec": "Tempo (s)", "protocol": "Protocolo"},
        template="plotly_white",
    )
    fig.write_html(os.path.join(PLOTS_DIR, "latency.html"))
    fig.write_image(os.path.join(PLOTS_DIR, "latency.png"), width=900, height=500)

    fig2, ax = plt.subplots(figsize=(9, 5))
    scenario_order = [SCENARIO_LABELS[s] for s in SCENARIOS]
    sns.boxplot(data=df, x="scenario_label", y="elapsed_sec",
                hue="protocol", palette=COLORS, order=scenario_order, ax=ax)
    ax.set_xlabel("Cenário de Rede")
    ax.set_ylabel("Tempo de Transferência (s)")
    ax.set_title("Distribuição do Tempo de Transferência")
    ax.legend(title="Protocolo")
    ax.grid(axis="y", alpha=0.4)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "latency_seaborn.png"), dpi=150)
    plt.close()
    print("[OK] Gráfico: latency")


def plot_retransmissions(df: pd.DataFrame):
    """Gráfico 3: Retransmissões R-UDP por cenário."""
    rudp = df[df["protocol"] == "R-UDP"].copy()
    if "retransmissions" not in rudp.columns or rudp["retransmissions"].isna().all():
        print("[SKIP] Dados de retransmissão não disponíveis")
        return

    stats = rudp.groupby("scenario")["retransmissions"].agg(["mean", "std"]).reset_index()
    stats["scenario_label"] = stats["scenario"].map(SCENARIO_LABELS)

    fig = go.Figure(go.Bar(
        x=stats["scenario_label"],
        y=stats["mean"],
        error_y=dict(type="data", array=stats["std"].fillna(0).tolist(), visible=True),
        marker_color="#FF5722",
        text=stats["mean"].round(1),
        textposition="outside",
    ))
    fig.update_layout(
        title="Retransmissões Médias — R-UDP por Cenário",
        xaxis_title="Cenário", yaxis_title="Nº de Retransmissões",
        template="plotly_white", font=dict(size=13),
    )
    fig.write_html(os.path.join(PLOTS_DIR, "retransmissions.html"))
    fig.write_image(os.path.join(PLOTS_DIR, "retransmissions.png"), width=800, height=450)
    print("[OK] Gráfico: retransmissions")


def plot_cross_validation(app_df: pd.DataFrame, tcpdump_df: pd.DataFrame):
    """
    Gráfico 4: Validação cruzada — bytes medidos pela aplicação vs TCPDump.
    Evidencia discrepâncias (overhead de protocolo, retransmissões).
    """
    if tcpdump_df.empty:
        print("[SKIP] CSVs do TCPDump não encontrados — pulando validação cruzada")
        return

    merged = app_df.groupby(["scenario", "protocol"])["bytes_sent"].mean().reset_index()
    merged.columns = ["scenario", "protocol", "app_bytes"]
    merged = merged.merge(
        tcpdump_df[["scenario", "protocol", "tcpdump_bytes"]],
        on=["scenario", "protocol"], how="left"
    )
    merged["overhead_pct"] = (
        (merged["tcpdump_bytes"] - merged["app_bytes"]) / merged["app_bytes"] * 100
    ).round(2)
    merged["scenario_label"] = merged["scenario"].map(SCENARIO_LABELS)

    fig = make_subplots(rows=1, cols=2, subplot_titles=[
        "Volume: Aplicação vs TCPDump (bytes)",
        "Overhead de Rede (%)"
    ])
    for proto, color in COLORS.items():
        sub = merged[merged["protocol"] == proto]
        fig.add_trace(go.Bar(
            name=f"{proto} — App", x=sub["scenario_label"], y=sub["app_bytes"],
            marker_color=color, opacity=0.6, showlegend=True,
        ), row=1, col=1)
        fig.add_trace(go.Bar(
            name=f"{proto} — TCPDump", x=sub["scenario_label"], y=sub["tcpdump_bytes"],
            marker_color=color, opacity=1.0, showlegend=True,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            name=f"{proto} — Overhead", x=sub["scenario_label"], y=sub["overhead_pct"],
            mode="lines+markers", marker=dict(color=color, size=8),
        ), row=1, col=2)

    fig.update_layout(
        title="Validação Cruzada: Aplicação vs TCPDump",
        template="plotly_white", font=dict(size=12), barmode="group"
    )
    fig.write_html(os.path.join(PLOTS_DIR, "cross_validation.html"))
    fig.write_image(os.path.join(PLOTS_DIR, "cross_validation.png"), width=1100, height=500)

    # Salva tabela de validação
    merged.to_csv(os.path.join(PLOTS_DIR, "cross_validation_table.csv"), index=False)
    print("[OK] Gráfico: cross_validation")
    print(merged[["scenario", "protocol", "app_bytes", "tcpdump_bytes", "overhead_pct"]].to_string(index=False))


def plot_heatmap(df: pd.DataFrame):
    """Gráfico 5: Heatmap de métricas normalizadas."""
    stats = df.groupby(["scenario", "protocol"]).agg(
        throughput=("throughput_mbps", "mean"),
        elapsed=("elapsed_sec", "mean"),
    ).reset_index()

    pivot_tp = stats.pivot(index="protocol", columns="scenario", values="throughput")
    pivot_el = stats.pivot(index="protocol", columns="scenario", values="elapsed")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    sns.heatmap(pivot_tp, annot=True, fmt=".1f", cmap="YlGn",
                ax=axes[0], linewidths=0.5)
    axes[0].set_title("Throughput Médio (Mbps)")
    axes[0].set_xlabel("Cenário")

    sns.heatmap(pivot_el, annot=True, fmt=".2f", cmap="YlOrRd_r",
                ax=axes[1], linewidths=0.5)
    axes[1].set_title("Tempo Médio de Transferência (s)")
    axes[1].set_xlabel("Cenário")

    plt.suptitle("Comparação de Desempenho TCP vs R-UDP", fontsize=14, y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "heatmap.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print("[OK] Gráfico: heatmap")


def print_summary(df: pd.DataFrame):
    print("\n" + "="*60)
    print(" RESUMO ESTATÍSTICO")
    print("="*60)
    summary = df.groupby(["protocol", "scenario"]).agg(
        n=("throughput_mbps", "count"),
        tp_mean=("throughput_mbps", "mean"),
        tp_std=("throughput_mbps", "std"),
        elapsed_mean=("elapsed_sec", "mean"),
    ).round(3)
    print(summary.to_string())
    print("="*60)


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("Carregando métricas...")
    app_df      = load_app_metrics()
    tcpdump_df  = load_tcpdump_metrics()

    print(f"Registros de aplicação: {len(app_df)}")
    print(f"Registros de TCPDump:   {len(tcpdump_df)}")

    print("\nGerando gráficos...")
    plot_throughput(app_df)
    plot_latency(app_df)
    plot_retransmissions(app_df)
    plot_cross_validation(app_df, tcpdump_df)
    plot_heatmap(app_df)
    print_summary(app_df)

    print(f"\nGráficos salvos em: {PLOTS_DIR}")
