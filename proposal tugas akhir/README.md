# 📘 Template LaTeX Skripsi & Proposal Tugas Akhir

**Program Studi Sarjana Sains Data – Universitas Negeri Surabaya (UNESA)**

Template ini dirancang untuk mempermudah penulisan Proposal dan Skripsi Tugas Akhir bagi mahasiswa S1 Sains Data FMIPA UNESA. Template memastikan keseragaman format sesuai pedoman penulisan skripsi UNESA.

> **Versi**: 2.5 (Desember 2025) - Versi pedoman penulisan skripsi unesa

---

## ✨ Fitur Utama

- ✅ **Zero Configuration**: Clone → Compile → Done!
- ✅ **Cross-platform**: Windows, macOS, Linux
- ✅ **Editor-agnostic**: VS Code, TeXstudio, Overleaf, Emacs, Vim
- ✅ **Smart Build**: `latexmk` auto-deteksi perubahan, skip jika tidak ada
- ✅ **Format UNESA**: Sesuai pedoman penulisan skripsi terbaru

---

## 🏗️ Arsitektur

Template ini dirancang agar **langsung jalan tanpa konfigurasi**:

```
┌─────────────────────────────────────────────────────────────────┐
│                    HOW IT WORKS                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  User clone repository                                          │
│         ↓                                                       │
│  latexmk -pdf ProposalTA.tex                                    │
│         ↓                                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ latexmk reads .latexmkrc (if exists)                    │   │
│  │   • Custom rules for glossaries                          │   │
│  │   • Dependency tracking                                  │   │
│  │   • Smart rebuild (skip if no changes)                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│         ↓                                                       │
│  PDF Generated! 🎉                                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 📋 Informasi Proyek

| Item              | Detail                                                                                                                                     |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| **Judul**         | Pengembangan _Knowledge Graph-Based RAG_ Menggunakan Pendekatan _Hybrid Vector-Graph Retrieval_ untuk Asisten Pencarian Referensi Akademik |
| **Penulis**       | Rizky Yanuar Kristianto (22031554017)                                                                                                      |
| **Program Studi** | Sarjana Sains Data                                                                                                                         |
| **Fakultas**      | Matematika dan Ilmu Pengetahuan Alam (FMIPA)                                                                                               |
| **Universitas**   | Universitas Negeri Surabaya                                                                                                                |
| **Tahun**         | 2025                                                                                                                                       |

---

## 📁 Struktur Proyek

```
proposal tugas akhir/
├── 📄 ProposalTA.tex           # File utama PROPOSAL (Bab 1-3)
├── 📄 Skripsi.tex              # File utama SKRIPSI (Bab 1-5)
├── 🎨 ProposalUnesa.cls        # Class file untuk Proposal
├── 🎨 SkripsiUnesa.cls         # Class file untuk Skripsi
├── 📝 DataSkripsi.tex          # Data identitas (nama, NIM, judul, dll)
├── 📚 Pustaka.bib              # Database referensi BibTeX
├── 📖 Istilah.tex              # Daftar istilah/glosarium
├── 🔧 unesa.bst                # Style bibliografi UNESA
│
├── 📂 Bab_1/                   # Pendahuluan
├── 📂 Bab_2/                   # Kajian Pustaka
├── 📂 Bab_3/                   # Metode Penelitian
├── 📂 Bab_4/                   # Hasil Penelitian (Skripsi)
├── 📂 Bab_5/                   # Simpulan (Skripsi)
├── 📂 Gambar/                  # Folder gambar
│
└── 🚫 .gitignore               # Ignore file temporary
```

### 📌 Konvensi Penamaan File

| Suffix   | Digunakan untuk | Bab     |
| -------- | --------------- | ------- |
| `*P.tex` | **Proposal**    | Bab 1-3 |
| `*.tex`  | **Skripsi**     | Bab 1-5 |

---

## 📝 File yang Perlu Diedit

### Untuk Proposal

| File                          | Fungsi                                 |
| ----------------------------- | -------------------------------------- |
| `DataSkripsi.tex`             | Data identitas (nama, NIM, judul, dll) |
| `Bab_1/PendahuluanP.tex`      | Bab I - Pendahuluan                    |
| `Bab_2/KajianPustakaP.tex`    | Bab II - Kajian Pustaka                |
| `Bab_3/MetodePenelitianP.tex` | Bab III - Metodologi                   |
| `Pustaka.bib`                 | Daftar referensi BibTeX                |
| `Istilah.tex`                 | Daftar istilah/glossary                |

### Untuk Skripsi (tambahan)

| File                         | Fungsi                                  |
| ---------------------------- | --------------------------------------- |
| `Bab_1/Pendahuluan.tex`      | Bab I - Pendahuluan (versi lengkap)     |
| `Bab_2/KajianPustaka.tex`    | Bab II - Kajian Pustaka (versi lengkap) |
| `Bab_3/MetodePenelitian.tex` | Bab III - Metodologi (versi lengkap)    |
| `Bab_4/HasilPenelitian.tex`  | Bab IV - Hasil dan Pembahasan           |
| `Bab_5/Simpulan.tex`         | Bab V - Simpulan dan Saran              |

---

## ⚠️ File yang TIDAK Boleh Diedit

- `ProposalUnesa.cls` - Document class Proposal
- `SkripsiUnesa.cls` - Document class Skripsi
- `unesa.bst` - Bibliography style
- `config/*` - Konfigurasi sistem

---

## 🚀 Quick Start (5 Menit!)

### Langkah 1: Install LaTeX Distribution

<details>
<summary><b>🪟 Windows (MiKTeX)</b></summary>

1. Download dari https://miktex.org/download
2. Jalankan installer
3. **Penting**: Centang ✅ "Always install missing packages on-the-fly"
4. Restart terminal/VS Code setelah install

</details>

<details>
<summary><b>🍎 macOS (MacTeX)</b></summary>

```bash
# Via Homebrew (recommended)
brew install --cask mactex

# Atau download dari https://tug.org/mactex/
```

</details>

<details>
<summary><b>🐧 Linux (TeX Live)</b></summary>

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install texlive-full latexmk

# Fedora
sudo dnf install texlive-scheme-full latexmk

# Arch Linux
sudo pacman -S texlive-most latexmk
```

</details>

### Langkah 2: Clone Repository

```bash
git clone https://github.com/rizkyyanuark/Tugas_Akhir.git
cd "Tugas_Akhir/proposal tugas akhir"

# Compile dengan latexmk (recommended)
latexmk -pdf ProposalTA.tex

# Atau manual
pdflatex ProposalTA
bibtex ProposalTA
pdflatex ProposalTA
pdflatex ProposalTA
```

### VS Code

1. Install extension **LaTeX Workshop**
2. Buka folder `proposal tugas akhir`
3. Buka `ProposalTA.tex`
4. Tekan **Ctrl+S** → Auto-compile!

---

## 📚 Manajemen Referensi

### Format BibTeX

Tambahkan referensi di `Pustaka.bib`:

```bibtex
@article{contoh2024,
  author  = {Nama Penulis},
  title   = {Judul Artikel},
  journal = {Nama Jurnal},
  year    = {2024},
  volume  = {10},
  pages   = {1--15},
  doi     = {10.1234/example}
}
```

### Reference Manager yang Direkomendasikan

- [Zotero](https://www.zotero.org/) – Gratis, open-source
- [Mendeley](https://www.mendeley.com/) – Integrasi cloud
- [JabRef](https://www.jabref.org/) – Native BibTeX editor

### Cara Sitasi

```latex
% Dalam teks
Menurut \cite{contoh2024}, hasil penelitian menunjukkan...

% Atau dengan natbib
\citep{contoh2024}  % (Penulis, 2024)
\citet{contoh2024}  % Penulis (2024)
```

---

## 🖥️ Setup Editor

<details>
<summary><b>VS Code (Recommended)</b></summary>

### Extensions yang Diperlukan

1. **LaTeX Workshop** (James Yu) - Compile dan preview
2. **LaTeX Utilities** (tecosaur) - Snippet dan autocompletion _(opsional)_

### Konfigurasi

✅ **Sudah otomatis!** File `.vscode/settings.json` sudah included.

### Keyboard Shortcuts

| Shortcut                             | Fungsi              |
| ------------------------------------ | ------------------- |
| `Ctrl+S`                             | Save & auto-compile |
| `Ctrl+Alt+V`                         | View PDF            |
| `Ctrl+Click` pada PDF                | Jump ke source code |
| `Ctrl+Shift+P` → "Build with recipe" | Pilih build mode    |

</details>

<details>
<summary><b>TeXstudio</b></summary>

1. Options → Configure TeXstudio → Build
2. Default Compiler: **PdfLaTeX**
3. Default Bibliography: **BibTeX**
4. Build & View: **F5**

</details>

<details>
<summary><b>Overleaf</b></summary>

1. Upload semua file ke project baru
2. Menu → Settings → Compiler: **pdfLaTeX**
3. Main document: **ProposalTA.tex** atau **Skripsi.tex**

</details>

<details>
<summary><b>Terminal (Vim/Emacs users)</b></summary>

```bash
# One-time full build
latexmk -pdf ProposalTA.tex

# Continuous build (watch mode)
latexmk -pvc -pdf ProposalTA.tex

# Clean
latexmk -C

# View PDF (Linux)
xdg-open ProposalTA.pdf

# View PDF (macOS)
open ProposalTA.pdf
```

</details>

---

## 🎨 Fitur Template

### ✅ Sudah Termasuk

- Format sesuai pedoman skripsi UNESA
- Halaman judul, persetujuan, daftar isi otomatis
- Daftar tabel dan gambar otomatis
- Daftar simbol dan glosarium
- Penomoran halaman (romawi untuk awal, arab untuk isi)
- Cross-referencing otomatis
- Bibliography style UNESA (`unesa.bst`)

### 📦 Package yang Digunakan

```latex
% Matematika
amsmath, amsthm, amssymb, mathtools

% Tabel
longtable, tabularx, multirow, array, hhline

% Gambar
graphicx, subcaption, float

% Referensi
natbib, hyperref

% Lainnya
tikz, pgfplots, listings, glossaries
```

---

## 🔧 Troubleshooting

<details>
<summary><b>❌ Error: Citation undefined</b></summary>

```bash
# Terminal
latexmk -pdf ProposalTA.tex

# VS Code: Pilih recipe "📚 Full Build (Bibliography)"
```

</details>

<details>
<summary><b>❌ Error: Missing package</b></summary>

**Penyebab**: Package LaTeX belum terinstall

**Solusi**:

```bash
# MiKTeX (Windows) - otomatis install
# Atau manual:
mpm --install nama_package

# TeX Live (Linux/Mac)
tlmgr install nama_package
```

</details>

<details>
<summary><b>❌ Error: Bibliography tidak muncul</b></summary>

**Penyebab**: BibTeX belum dijalankan

**Solusi**:

```bash
pdflatex ProposalTA
bibtex ProposalTA
pdflatex ProposalTA
pdflatex ProposalTA

# Atau gunakan latexmk (otomatis)
latexmk -pdf ProposalTA.tex
```

</details>

<details>
<summary><b>⚠️ Warning: Infinite glue shrinkage / Underfull hbox</b></summary>

**Status**: Warning ini **normal** dan tidak mempengaruhi output PDF.

**Penyebab**: Layout adjustment pada tabel/longtable yang split antar halaman.

</details>

<details>
<summary><b>⏱️ Compile sangat lambat (>2 menit)</b></summary>

**Penyebab**: Full build dengan semua bab

**Solusi**:

1. Gunakan `\includeonly{Bab_X/...}` saat editing
2. Pilih recipe "⚡ Quick Build" di VS Code
3. Jika pakai OneDrive, pertimbangkan pindah ke folder lokal

</details>

<details>
<summary><b>❌ makeglossaries tidak jalan</b></summary>

**Penyebab**: Perl tidak terinstall (Windows)

**Solusi Windows**:

1. Install Strawberry Perl: https://strawberryperl.com/
2. Restart terminal/VS Code
3. Verify: `perl --version`

</details>

---

## 📬 Kontak

**Penulis:** Rizky Yanuar Kristianto  
**Email:** rizky.22017@mhs.unesa.ac.id  
**GitHub:** [@rizkyyanuark](https://github.com/rizkyyanuark)

**Pembimbing:**

1. Ibnu Febry K., S.Kom., M.Sc., Ph.D.
2. Hasanuddin Al-Habib, M.Si.

---

## 📄 Lisensi

Template ini dapat digunakan dan dimodifikasi untuk keperluan akademik di lingkungan UNESA.

---

## 🤝 Kontribusi

Kontribusi sangat diterima! Silakan:

1. **Fork** repository ini
2. Buat **branch** baru: `git checkout -b fitur-baru`
3. **Commit** perubahan: `git commit -m "Tambah fitur X"`
4. **Push** ke branch: `git push origin fitur-baru`
5. Buat **Pull Request**

### Yang Bisa Dikontribusikan

- 🐛 Bug fixes pada class file
- 📝 Perbaikan dokumentasi
- 🎨 Improvement template layout
- 🔧 Optimisasi build process

---

## 📊 Kompatibilitas

| Platform | LaTeX Distribution | Status         |
| -------- | ------------------ | -------------- |
| Windows  | MiKTeX             | ✅ Tested      |
| Windows  | TeX Live           | ✅ Tested      |
| macOS    | MacTeX             | ✅ Should work |
| Linux    | TeX Live           | ✅ Should work |
| Online   | Overleaf           | ✅ Tested      |

| Editor                   | Status                   |
| ------------------------ | ------------------------ |
| VS Code + LaTeX Workshop | ✅ Fully configured      |
| TeXstudio                | ✅ Works with .latexmkrc |
| Overleaf                 | ✅ Works                 |
| Emacs/Vim                | ✅ Works with latexmk    |

---

_Last updated: Desember 2025_
