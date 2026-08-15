from __future__ import annotations

import logging
from typing import Any, Dict, List, Set, Optional

from ..config import STRICT_AFFILIATION
from ..utils.utils import make_lecturer_entry

logger = logging.getLogger(__name__)

try:
    from pddiktipy import api as pddikti_api
except ImportError:
    pddikti_api = None
    logger.warning("pddiktipy not installed. PddiktiClient will be unavailable.")

class PddiktiClient:
    """
    Client for PDDIKTI API to fetch national lecturer data.
    """
    
    def __init__(self) -> None:
        self.available = pddikti_api is not None

    def search_lecturers(self, active_configs: List[tuple]) -> List[Dict[str, Any]]:
        """
        Search for lecturers based on program study configurations.
        
        Args:
            active_configs: List of (code, name, url, keyword, parser_key) tuples.
            
        Returns:
            List[Dict[str, Any]]: Standardized lecturer records.
        """
        if not self.available:
            logger.warning("PDDIKTI API not available. Skipping search.")
            return []
        
        results: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        
        # pddikti_api() is used as a context manager if supported, 
        # but the original code uses 'with pddikti_api() as client'.
        try:
            with pddikti_api() as client:
                for cfg in active_configs:
                    prodi_code, prodi_name, _, keyword, _ = cfg
                    query = f"{keyword} Universitas Negeri Surabaya"
                    logger.info(f"PDDIKTI: Searching for '{keyword}' at UNESA...")
                    
                    try:
                        res = client.search_all(query) or {}
                        dosen_list = res.get("dosen", [])
                        
                        count = 0
                        for d in dosen_list:
                            # Filter by exact affiliation
                            if d.get('nama_pt') != STRICT_AFFILIATION:
                                continue
                            
                            # Filter by prodi keyword to ensure correct department
                            raw_prodi = d.get("nama_prodi", "")
                            if keyword.lower() not in raw_prodi.lower():
                                continue
                            
                            # Deduplicate by NIDN and Name
                            nidn = d.get('nidn')
                            name = d.get('nama', '')
                            unique_key = f"{nidn}_{name}"
                            
                            if unique_key in seen_ids:
                                continue
                            seen_ids.add(unique_key)
                            
                            # Normalize name capitalization if it's all uppercase
                            if name and name.isupper():
                                name = name.title()
                                
                            entry = make_lecturer_entry(name, nip=None, nidn=nidn)
                            entry.update({
                                'nama_pt': d.get('nama_pt'),
                                'prodi_code': prodi_code,
                                'prodi_name': prodi_name,
                                'prodi_pddikti': raw_prodi,
                                'source': 'PDDIKTI'
                            })
                            results.append(entry)
                            count += 1
                            
                        logger.info(f"      Found {count} lecturers for {prodi_name}")
                        
                    except Exception as e:
                        logger.error(f"      PDDIKTI API Search Error for {prodi_name}: {e}")
                        
        except Exception as e:
            logger.error(f"Could not initialize PDDIKTI client: {e}")
            
        return results
