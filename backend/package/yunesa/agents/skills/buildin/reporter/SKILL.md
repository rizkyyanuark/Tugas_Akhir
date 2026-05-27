---
name: reporter
description: "Membantu membuat laporan berbasis SQL, merangkum hasil query database, dan menyajikan visualisasi data bila tool pendukung tersedia."
---

# SQL Reporter Skill

Gunakan skill ini ketika pengguna meminta laporan berbasis data dari database relasional, terutama ketika perlu membuat query SQL, membaca hasilnya, lalu menyusun ringkasan atau visualisasi.

## Alur Kerja

1. Pahami pertanyaan pengguna dan tentukan metrik atau data yang dibutuhkan.
2. Identifikasi tabel, kolom, dan relasi yang relevan.
3. Buat query SQL yang jelas, efisien, dan sesuai konteks.
4. Jalankan query menggunakan tool database yang tersedia.
5. Ringkas hasil query dalam bentuk laporan yang mudah dibaca.
6. Buat visualisasi data bila tool chart tersedia dan memang membantu pemahaman.

## Batasan

- Hindari query yang terlalu luas atau melakukan full table scan tanpa alasan kuat.
- Jangan mengubah data kecuali pengguna secara eksplisit meminta operasi tulis.
- Jangan menampilkan SQL mentah jika pengguna hanya meminta insight akhir.
- Jelaskan keterbatasan data jika hasil query tidak cukup mendukung kesimpulan.

## Tool Yang Dapat Digunakan

- MySQL tool untuk menjalankan query SQL.
- Charts MCP untuk membuat visualisasi data.
- Retrieval tool bila perlu melengkapi konteks laporan.
