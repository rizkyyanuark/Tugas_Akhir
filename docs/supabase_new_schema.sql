-- ==============================================================================
-- UNESA PAPERS ETL - INDUSTRY-GRADE DATA WAREHOUSE SCHEMA
-- ==============================================================================
-- Panduan: 
-- 1. Hapus tabel lama (jika ada) di Supabase (Pastikan Anda sudah membackup data jika perlu).
-- 2. Jalankan seluruh script SQL ini di SQL Editor Supabase.
-- ==============================================================================

-- Drop existing tables (Hati-hati! Ini akan menghapus tabel lama beserta datanya)
DROP TABLE IF EXISTS paper_lecturers CASCADE;
DROP TABLE IF EXISTS papers CASCADE;
DROP TABLE IF EXISTS lecturers CASCADE;

-- 1. Tabel Dosen (NIP sebagai Primary Key langsung)
CREATE TABLE lecturers (
    nip         TEXT PRIMARY KEY,  -- UPSERT TARGET LANGSUNG!
    nama_dosen  TEXT NOT NULL,
    nama_norm   TEXT,
    nidn        TEXT,
    prodi       TEXT,
    scopus_id   TEXT,
    scholar_id  TEXT,
    sinta_id    TEXT,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Tabel Papers (paper_id sebagai Deterministic Hash PK)
CREATE TABLE papers (
    paper_id        TEXT PRIMARY KEY, -- UPSERT TARGET (Hash MD5 dari Python)
    doi             TEXT,             -- DOI tetap disimpan, tapi boleh kosong
    title           TEXT NOT NULL,
    abstract        TEXT,
    year            INTEGER,
    journal         TEXT,
    document_type   TEXT,
    authors         TEXT,
    author_ids      TEXT, 
    keywords        TEXT,
    link            TEXT,
    tldr            TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Junction Table (Relasi M:M menggunakan Natural Keys/Hash)
CREATE TABLE paper_lecturers (
    paper_id    TEXT REFERENCES papers(paper_id) ON DELETE CASCADE,
    nip         TEXT REFERENCES lecturers(nip) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (paper_id, nip) -- Constraint untuk mencegah relasi duplikat
);

-- 4. Matikan RLS agar script Python ETL bisa UPSERT tanpa masalah otorisasi Row-Level
ALTER TABLE lecturers DISABLE ROW LEVEL SECURITY;
ALTER TABLE papers DISABLE ROW LEVEL SECURITY;
ALTER TABLE paper_lecturers DISABLE ROW LEVEL SECURITY;

-- SELESAI!
