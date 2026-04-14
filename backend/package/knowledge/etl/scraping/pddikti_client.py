# knowledge/etl/scraping/pddikti_client.py
"""PDDIKTI API Client — fetches lecturer data from the national database."""

from .config import STRICT_AFFILIATION
from .utils import make_entry

try:
    from pddiktipy import api as pddikti_api
except ImportError:
    pddikti_api = None


class PddiktiClient:
    def __init__(self):
        self.available = pddikti_api is not None
        if not self.available:
            print("⚠️ PDDIKTI API not installed.")

    def search_lecturers(self, active_configs):
        if not self.available: return []
        
        results = []
        seen_ids = set()
        
        with pddikti_api() as client:
            for cfg in active_configs:
                code, name, _, keyword, _ = cfg
                query = f"{keyword} Universitas Negeri Surabaya"
                print(f"   🔍 PDDIKTI Search: '{query}'...")
                
                try:
                    res = client.search_all(query) or {}
                    dosen_list = res.get("dosen", [])
                    
                    count = 0
                    for d in dosen_list:
                        if d.get('nama_pt') != STRICT_AFFILIATION: continue
                        
                        raw_prodi = d.get("nama_prodi", "")
                        if keyword.lower() not in raw_prodi.lower(): continue
                        
                        # Unique ID (NIDN + Name)
                        unique_key = f"{d.get('nidn')}_{d.get('nama')}"
                        if unique_key in seen_ids: continue
                        seen_ids.add(unique_key)
                        
                        # Caps Fix
                        raw_name = d.get('nama', '')
                        if raw_name and raw_name.isupper():
                            raw_name = raw_name.title()
                            
                        entry = make_entry(raw_name, nip=None, nidn=d.get('nidn'))
                        entry.update({
                            'nama_pt': d.get('nama_pt'),
                            'prodi_code': code,
                            'prodi_name': name,
                            'prodi_pddikti': raw_prodi,
                            'source': 'PDDIKTI'
                        })
                        results.append(entry)
                        count += 1
                    print(f"      ✅ Added: {count}")
                    
                except Exception as e:
                    print(f"      ❌ API Error: {e}")
        return results
