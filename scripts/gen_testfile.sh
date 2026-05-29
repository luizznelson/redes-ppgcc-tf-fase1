#!/bin/bash
# gen_testfile.sh — Gera arquivo binário aleatório para os testes
# Uso: ./gen_testfile.sh [size_mb]

SIZE_MB=${1:-10}
OUT="/tmp/testfile.bin"

echo "Gerando $SIZE_MB MB em $OUT ..."
dd if=/dev/urandom of="$OUT" bs=1M count="$SIZE_MB" status=progress
echo "MD5: $(md5sum $OUT)"
echo "Tamanho: $(du -sh $OUT | cut -f1)"
