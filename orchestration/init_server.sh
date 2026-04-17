#!/bin/bash

# 1. Buat folder untuk menampung data hasil ETL agar tidak campur dengan mahasiswa lain
mkdir -p /home/shared/vols/etl/unesa_research_data
chmod -R 777 /home/shared/vols/etl/unesa_research_data

# 2. Buat network docker (jika belum ada)
docker network create unesa_etl_network || true

# 3. Buat volume docker (jika belum ada)
docker volume create unesa_etl_data || true

echo "=============================================="
echo "✅ SETUP BERHASIL!"
echo "Folder, Network, dan Volume sudah siap."
echo "=============================================="
