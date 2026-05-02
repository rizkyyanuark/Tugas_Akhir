import os
import re
import logging
from typing import List, Dict, Any
from supabase import create_client, Client

logger = logging.getLogger(__name__)

class DataLoader:
    def __init__(self, supabase_url: str = None, supabase_key: str = None):
        """
        Inisialisasi koneksi ke Supabase.
        Jika url/key tidak diberikan, akan mengambil dari environment variables.
        """
        self.url = supabase_url or os.environ.get("SUPABASE_URL")
        self.key = supabase_key or os.environ.get("SUPABASE_KEY")
        
        if not self.url or not self.key:
            raise ValueError("Supabase credentials tidak ditemukan. Pastikan SUPABASE_URL dan SUPABASE_KEY telah di-set di environment atau kg.env")
            
        self.supabase: Client = create_client(self.url, self.key)
        logger.info(f"Connected to Supabase at {self.url}")

    def fetch_lecturers(self) -> List[Dict[str, Any]]:
        """
        Mengambil semua data dosen (Lecturers) dari tabel 'lecturers'.
        """
        logger.info("Fetching lecturers data from Supabase...")
        response = self.supabase.table("lecturers").select("*").execute()
        data = response.data
        logger.info(f"Found {len(data)} lecturers.")
        return data

    def fetch_papers(self) -> List[Dict[str, Any]]:
        """
        Mengambil semua data paper dari tabel 'papers' dan membersihkan field (Incremental Update logic diserahkan ke GraphBuilder).
        """
        logger.info("Fetching papers data from Supabase...")
        response = self.supabase.table("papers").select("*").execute()
        raw_papers = response.data
        logger.info(f"Found {len(raw_papers)} papers. Processing fields...")
        
        processed_papers = []
        for paper in raw_papers:
            # 1. Parse Authors
            authors_list = [a.strip() for a in paper.get("authors", "").split(",") if a.strip()]
            paper["authors_list"] = authors_list
            
            # 2. Parse Author IDs
            author_ids = [aid.strip() for aid in paper.get("author_ids", "").split(",") if aid.strip()]
            paper["author_ids_list"] = author_ids
            
            # 3. Clean Journal / Venue Name
            raw_journal = paper.get("journal", "")
            paper["venue_clean"] = self._clean_journal_name(raw_journal)
            
            # 4. Clean Keywords
            raw_keywords = paper.get("keywords", "")
            paper["keywords_clean"] = self._clean_keywords(raw_keywords)
            
            processed_papers.append(paper)
            
        return processed_papers

    def fetch_taxonomy_translations(self) -> Dict[str, str]:
        """
        Mengambil mapping translasi dari tabel 'taxonomy_translations'.
        Jika tabel belum ada atau gagal, return dictionary kosong.
        """
        logger.info("Fetching taxonomy translations from Supabase...")
        translation_map = {}
        try:
            response = self.supabase.table("taxonomy_translations").select("*").execute()
            for row in response.data:
                indo_term = row.get("indonesian_term", "").strip().lower()
                eng_term = row.get("english_term", "").strip().lower()
                if indo_term and eng_term:
                    translation_map[indo_term] = eng_term
            logger.info(f"Loaded {len(translation_map)} translation mappings.")
        except Exception as e:
            logger.warning(f"Failed to fetch taxonomy_translations (mungkin tabel belum dibuat): {e}")
        
        return translation_map

    def _clean_journal_name(self, raw_name: str) -> str:
        """
        Membersihkan nama jurnal dari page numbers, tahun, dan karakter berlebih.
        Contoh: "Journal of Electronics, Electromedical Engineering, and Medical Informa... 2026 611-619"
        """
        if not raw_name:
            return "Unknown Venue"
            
        name = str(raw_name)
        
        # Hapus page numbers seperti "611-619" atau "611 - 619"
        name = re.sub(r'\b\d+\s*-\s*\d+\b', '', name)
        
        # Hapus tahun (4 digit angka seperti 19xx atau 20xx)
        name = re.sub(r'\b(19|20)\d{2}\b', '', name)
        
        # Hapus elipsis
        name = name.replace('...', '').replace('..', '')
        
        # Hapus whitespace ganda
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Hapus tanda baca di akhir/awal (kecuali dibutuhkan)
        name = name.strip(',.- ')
        
        return name if name else "Unknown Venue"

    def _clean_keywords(self, raw_keywords: str) -> List[str]:
        """
        Membersihkan keyword, memisahkan dengan koma/semicolon, dan lowercase.
        """
        if not raw_keywords:
            return []
            
        # Pisahkan menggunakan koma atau titik koma
        parts = re.split(r'[,;]', str(raw_keywords))
        
        cleaned = set()
        for p in parts:
            p = p.strip().lower()
            # Hapus noise yang umum muncul akibat scraping
            p = p.replace("downloads download data", "").strip()
            p = p.replace("download data", "").strip()
            p = p.replace("downloads", "").strip()
            
            if p:
                cleaned.add(p)
                
        return list(cleaned)

if __name__ == "__main__":
    # Test Data Loader (Pastikan ada .env atau export variable)
    logging.basicConfig(level=logging.INFO)
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), "../kg.env")
    load_dotenv(env_path)
    
    loader = DataLoader()
    lecturers = loader.fetch_lecturers()
    papers = loader.fetch_papers()
    translations = loader.fetch_taxonomy_translations()
    
    if papers:
        print(f"\nContoh Paper Journal Asli: {papers[0].get('journal')}")
        print(f"Contoh Paper Journal Bersih: {papers[0].get('venue_clean')}")
        print(f"Contoh Keywords Asli: {papers[0].get('keywords')}")
        print(f"Contoh Keywords Bersih: {papers[0].get('keywords_clean')}")
