# 🚀 VAST.AI GPU INSTANCE SETUP GUIDE (UNESA TUGAS AKHIR)
**Panduan Copas Step-by-Step dari Nol hingga Siap Pakai di JupyterLab / VS Code**

Panduan ini dibuat khusus agar Anda dapat dengan mudah memasang GPU server di Vast.ai, melakukan otomatisasi environment dengan `uv`, dan mengeksekusi notebook [constuction_knowledge_graph.ipynb](file:///c:/Users/rizky/Documents/GitHub/Tugas_Akhir/notebooks/build-graph/constuction_knowledge_graph.ipynb) menggunakan **GPU RTX 5070** tanpa biaya sewa storage saat server sedang dimatikan.

---

## 📌 PRASYARAT (Cukup Sekali di Laptop)

### 1. Cek SSH Key di Laptop (PowerShell)
Buka PowerShell di laptop Anda, jalankan:
```powershell
cat C:\Users\rizky\.ssh\id_rsa.pub
```
*(Jika belum ada, buat kunci baru dengan perintah: `ssh-keygen -t rsa -b 4096 -f C:\Users\rizky\.ssh\id_rsa -N '""'`)*.

### 2. Daftarkan Public Key ke Vast.ai
1. Salin seluruh teks output `id_rsa.pub` (berawalan `ssh-rsa AAAAB3...`).
2. Buka **Vast.ai Console** $\rightarrow$ **Account Settings** (atau klik ikon Kunci di card instance).
3. Paste di kolom **New SSH Key** $\rightarrow$ Klik **+ Add SSH Key**.

---

## 🛠️ STEP 1: RENT INSTANCE BARU DI VAST.AI

1. Buka Vast.ai Console $\rightarrow$ **CREATE**.
2. **Pilih Template:** `vastai/pytorch_cuda-13.2.1-auto/jupyter` (atau PyTorch 2.x CUDA).
3. **Pilih GPU:** Pilih GPU berdaya tinggi (misal **RTX 5070 / RTX 4090**).
4. Klik **RENT**.

---

## 🔌 STEP 2: KONFIGURASI SSH CONFIG LAPTOP

Buka file **`C:\Users\rizky\.ssh\config`** di laptop Anda, lalu sesuaikan IP & Port Direct dari Vast.ai:

```text
Host vast
    HostName IP_SERVER_VAST        # Contoh: 108.39.26.2
    User root
    Port PORT_DIRECT_VAST          # Contoh: 49309
    IdentityFile C:\Users\rizky\.ssh\id_rsa
    LocalForward 8080 localhost:8080
    ServerAliveInterval 60
```

---

## 💻 STEP 3: LOGIN SSH KE VAST.AI

Buka PowerShell di laptop Anda, ketik 2 kata sederhana ini:

```powershell
ssh vast
```
*(Anda akan otomatis login ke dalam terminal Linux GPU Vast.ai).*

---

## ⚡ STEP 4: SETUP ENVIRONMENT & INSTALL LIBRARY (1-CLICK COPAS)

Setelah masuk ke dalam terminal Vast.ai (`root@C.XXXX:/#`), **copy & paste seluruh blok kode ini sekaligus**:

```bash
# 1. Masuk ke folder workspace utama
cd /workspace

# 2. Buat Virtual Environment rapi dengan Python 3.12
uv venv .venv --python 3.12

# 3. Aktifkan Virtual Environment
source .venv/bin/activate

# 4. Install PyTorch GPU & Seluruh Pustaka Knowledge Graph
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
uv pip install supabase rdflib neo4j pymilvus python-dotenv pyyaml networkx pandas matplotlib ipykernel

# 5. Daftarkan Kernel Jupyter bernama "python3 (5070)"
python -m ipykernel install --prefix=/workspace/.venv --name=python3-5070 --display-name "python3 (5070)"
```

---

## 🌐 STEP 5: MENJALANKAN NOTEBOOK DENGAN GPU VAST.AI

### **Opsi A: Menggunakan VS Code (Rekomendasi Utama)**
1. Buka notebook lokal Anda [constuction_knowledge_graph.ipynb](file:///c:/Users/rizky/Documents/GitHub/Tugas_Akhir/notebooks/build-graph/constuction_knowledge_graph.ipynb) di **VS Code**.
2. Di pojok kanan atas notebook, klik **Select Kernel** $\rightarrow$ **Existing Jupyter Server...**
3. Dapatkan token Vast.ai via terminal SSH (`jupyter server list`).
4. Paste URL Server:
   ```text
   https://localhost:8080/?token=TOKEN_JUPYTER_VAST_AI
   ```

### **Opsi B: Menggunakan PowerShell Laptop (`uv run`)**
Buka PowerShell di laptop Anda pada folder `notebooks`:
```powershell
uv run --with jupyterlab jupyter lab --GatewayClient.url="https://localhost:8080" --GatewayClient.auth_token="TOKEN_JUPYTER_VAST_AI" --GatewayClient.validate_cert=False
```

---

## 🧪 STEP 6: VERIFIKASI GPU DI CELL NOTEBOOK

Di cell pertama notebook Anda, jalankan kode ini untuk memastikan GPU aktif:

```python
import torch
print("CUDA Available :", torch.cuda.is_available())
print("GPU Name       :", torch.cuda.get_device_name(0))
```

*Output Sukses:*
```text
CUDA Available : True
GPU Name       : NVIDIA GeForce RTX 5070
```

---

## 🗑️ STEP 7: HAPUS INSTANCE AGAR TAGIHAN $0.00 (RP 0)

Bila sudah selesai bereksperimen:
1. Buka Vast.ai Console $\rightarrow$ Klik ikon **Destroy (Place Trash Can)**.
2. Tagihan harian Anda langsung **berhenti 100% (Rp 0)** tanpa potongan sewa storage $0.21/hari.
3. Saat butuh GPU lagi di masa depan, ulangi **Step 1 sampai Step 5** (hanya memakan waktu 15 detik!).
