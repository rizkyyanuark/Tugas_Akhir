#!/bin/bash
# ==========================================
# 🚀 AWS EC2 SWAP SETUP (4GB)
# ==========================================
# This script enables 4GB of SWAP on 4GB RAM 
# instance to prevent Out of Memory (OOM).

SWAP_FILE="/swapfile"
SWAP_SIZE="4G"

if [ -f "$SWAP_FILE" ]; then
    CURRENT_SIZE=$(du -m $SWAP_FILE | cut -f1)
    if [ "$CURRENT_SIZE" -lt 4000 ]; then
        echo "⚠️ Swap file is smaller than 4G. Recreating..."
        sudo swapoff $SWAP_FILE || true
        sudo rm -f $SWAP_FILE
    else
        echo "✅ Swap file already exists and is 4G. Skipping."
        exit 0
    fi
fi

echo "📦 Creating $SWAP_SIZE swap file..."
sudo fallocate -l $SWAP_SIZE $SWAP_FILE
sudo chmod 600 $SWAP_FILE
sudo mkswap $SWAP_FILE
sudo swapon $SWAP_FILE

# Make it persistent after reboot (idempotent — only add if not already present)
grep -q "$SWAP_FILE" /etc/fstab || echo "$SWAP_FILE none swap sw 0 0" | sudo tee -a /etc/fstab

echo "🚀 SWAP Status:"
free -h
swapon --show
