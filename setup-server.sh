#!/bin/bash
# ══════════════════════════════════════════════════════════════
# setup-server.sh — Persiapan Server AWS EC2 untuk Tugas Akhir
# ══════════════════════════════════════════════════════════════
# Script ini dijalankan otomatis oleh GitHub Actions CI/CD,
# atau manual saat setup pertama kali:
#   chmod +x setup-server.sh && ./setup-server.sh
#
# File .env di-inject otomatis oleh CI/CD dari GitHub Secrets.
# ══════════════════════════════════════════════════════════════

set -e

echo "══════════════════════════════════════════════════════════════"
echo "  🚀 Setup Server Tugas Akhir — AWS EC2"
echo "══════════════════════════════════════════════════════════════"

# --- 1. Detect Public IP (IMDSv2 compatible) ---
echo ""
echo "[1/5] Mendeteksi IP Public server..."
# IMDSv2 requires a token for security. Fallback to IMDSv1 if token fails.
IMDS_TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null || echo "")

if [ -n "$IMDS_TOKEN" ]; then
    HOST_IP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" \
      http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "GAGAL_DETEKSI")
else
    HOST_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "GAGAL_DETEKSI")
fi
echo "      IP Public: $HOST_IP"

# --- 2. Create required directories ---
echo ""
echo "[2/5] Membuat direktori yang dibutuhkan..."
mkdir -p data saves models orchestration/dags
echo "      ✓ data/ saves/ models/ orchestration/dags/"

# --- 3. Add swap (if not exists) ---
echo ""
echo "[3/5] Mengecek swap memory..."
if [ "$(swapon --show | wc -l)" -lt 2 ]; then
    echo "      Menambahkan 4GB swap..."
    sudo fallocate -l 4G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    # Only add to fstab if not already there
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "      ✓ Swap 4GB aktif"
else
    echo "      ✓ Swap sudah ada"
fi

# --- 4. Resize filesystem (if EBS was expanded) ---
echo ""
echo "[4/5] Memeriksa filesystem..."
ROOT_DEVICE=$(df / | tail -1 | awk '{print $1}')
if command -v growpart &> /dev/null; then
    DISK_DEVICE=$(echo "$ROOT_DEVICE" | sed 's/p\?[0-9]*$//')
    PARTITION_NUM=$(echo "$ROOT_DEVICE" | grep -o '[0-9]*$')
    sudo growpart "$DISK_DEVICE" "$PARTITION_NUM" 2>/dev/null || true
    sudo resize2fs "$ROOT_DEVICE" 2>/dev/null || true
fi
echo "      ✓ Filesystem: $(df -h / | tail -1 | awk '{print $2}') total, $(df -h / | tail -1 | awk '{print $4}') free"

# --- 5. Process .env for production ---
echo ""
echo "[5/5] Mengecek file .env..."
if [ ! -f .env ]; then
    echo "      ❌ File .env BELUM ADA!"
    echo "      File .env akan di-inject otomatis oleh GitHub Actions CI/CD."
    echo "      Jika setup manual, copy dari laptop:"
    echo ""
    echo "      scp -i key.pem .env ubuntu@${HOST_IP}:~/Tugas_Akhir/.env"
    echo ""
    exit 1
else
    # Update HOST_IP jika masih placeholder
    if grep -q "your-ec2-ip" .env; then
        sed -i "s/HOST_IP=your-ec2-ip/HOST_IP=$HOST_IP/" .env
        echo "      ✓ HOST_IP diupdate ke $HOST_IP"
    fi

    # Update BACKEND_RELOAD ke false untuk production
    sed -i "s/BACKEND_RELOAD=true/BACKEND_RELOAD=false/" .env

    # Flatten ${GLOBAL_PASSWORD} references ke nilai aslinya
    GLOBAL_PW=$(grep "^GLOBAL_PASSWORD=" .env | cut -d'=' -f2)
    if [ -n "$GLOBAL_PW" ]; then
        sed -i "s/\${GLOBAL_PASSWORD}/$GLOBAL_PW/g" .env
        echo "      ✓ Variabel \${GLOBAL_PASSWORD} di-resolve ke nilai asli"
    fi

    # Flatten ${POSTGRES_USER} and ${POSTGRES_DB} for POSTGRES_URL
    PG_USER=$(grep "^POSTGRES_USER=" .env | cut -d'=' -f2)
    PG_DB=$(grep "^POSTGRES_DB=" .env | cut -d'=' -f2)
    if [ -n "$PG_USER" ]; then
        sed -i "s/\${POSTGRES_USER}/$PG_USER/g" .env
        echo "      ✓ Variabel \${POSTGRES_USER} di-resolve"
    fi
    if [ -n "$PG_DB" ]; then
        sed -i "s/\${POSTGRES_DB}/$PG_DB/g" .env
        echo "      ✓ Variabel \${POSTGRES_DB} di-resolve"
    fi

    echo "      ✓ File .env siap untuk production"
fi

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "  ✅ Setup selesai! Jalankan deployment dengan:"
echo ""
echo "  docker compose -f docker-compose.prod.yml --profile etl up -d --build"
echo ""
echo "  Akses aplikasi:"
echo "    Frontend : http://$HOST_IP"
echo "    Airflow  : http://$HOST_IP:8080"
echo "══════════════════════════════════════════════════════════════"
