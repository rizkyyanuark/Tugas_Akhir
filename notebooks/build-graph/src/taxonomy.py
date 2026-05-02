import os
import json
import logging
import difflib
import requests
import rdflib
from rdflib.namespace import SKOS
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

class TaxonomyEngine:
    def __init__(self, thesaurus_path: str):
        self.thesaurus_path = thesaurus_path
        self.graph = rdflib.Graph()
        
        self.pref_labels = {}  # { lower_term: original_term }
        self.alt_labels = {}   # { lower_alt: original_pref }
        
        self.term_list = []    # list of original_terms for vector search
        
        self.encoder = None
        self.term_embeddings = None
        
        self.llm_cache_path = os.path.join(os.path.dirname(__file__), "../config/llm_cache.json")
        self.llm_cache = self._load_cache()
        
        self._load_thesaurus()

    def _load_thesaurus(self):
        logger.info(f"Loading SKOS Thesaurus from {self.thesaurus_path}...")
        if not os.path.exists(self.thesaurus_path):
            logger.warning(f"Thesaurus file {self.thesaurus_path} not found. Skipping SKOS load.")
            return

        self.graph.parse(self.thesaurus_path, format="ttl")
        logger.info(f"Loaded {len(self.graph)} triples.")
        
        # Build indexes
        for concept in self.graph.subjects(rdflib.RDF.type, SKOS.Concept):
            # PrefLabel
            for pref in self.graph.objects(concept, SKOS.prefLabel):
                pref_str = str(pref)
                self.pref_labels[pref_str.lower()] = pref_str
                self.term_list.append(pref_str)
                
            # AltLabel
            for alt in self.graph.objects(concept, SKOS.altLabel):
                alt_str = str(alt)
                # Find corresponding prefLabel
                prefs = list(self.graph.objects(concept, SKOS.prefLabel))
                if prefs:
                    self.alt_labels[alt_str.lower()] = str(prefs[0])

    def _load_cache(self) -> Dict[str, str]:
        if os.path.exists(self.llm_cache_path):
            try:
                with open(self.llm_cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Error loading LLM cache: {e}")
        return {}

    def _save_cache(self):
        os.makedirs(os.path.dirname(self.llm_cache_path), exist_ok=True)
        with open(self.llm_cache_path, 'w', encoding='utf-8') as f:
            json.dump(self.llm_cache, f, indent=2)

    def _init_encoder(self):
        if self.encoder is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info("Initializing SentenceTransformer for Rule 4 (Vector Search)...")
                self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("Encoding all IEEE terms...")
                self.term_embeddings = self.encoder.encode(self.term_list, convert_to_tensor=True)
            except ImportError:
                logger.error("sentence-transformers not installed. Rule 4 will fail.")
                raise

    def _call_llm_fallback(self, keyword: str) -> str:
        # Check cache
        if keyword in self.llm_cache:
            return self.llm_cache[keyword]
            
        # Use Groq API
        groq_key = os.environ.get("GROQ_API_KEY")
        if not groq_key:
            logger.warning("GROQ_API_KEY not found. Skipping Rule 5 (LLM Fallback).")
            return None
            
        logger.info(f"Calling LLM Fallback for: '{keyword}'")
        
        prompt = (
            f"Map the academic keyword '{keyword}' to the most appropriate IEEE Thesaurus term. "
            "Reply ONLY with the exact IEEE term, nothing else. If unsure, reply with 'UNMAPPED'."
        )
        
        headers = {
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 20
        }
        
        try:
            resp = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()["choices"][0]["message"]["content"].strip()
            
            # Verify if result is valid term
            if result.lower() in self.pref_labels:
                matched_term = self.pref_labels[result.lower()]
                self.llm_cache[keyword] = matched_term
                self._save_cache()
                return matched_term
            else:
                self.llm_cache[keyword] = "UNMAPPED"
                self._save_cache()
                return None
        except Exception as e:
            logger.error(f"LLM Fallback failed: {e}")
            return None

    def map_keyword(self, keyword: str) -> Tuple[str, str]:
        """
        Maps a given English keyword to the IEEE taxonomy using the 5 Rules.
        Returns: (Mapped_Term, Rule_Applied)
        """
        k_lower = keyword.strip().lower()
        if not k_lower:
            return ("UNMAPPED", "Rule 6 (Empty)")
            
        # Rule 1: Exact Match (Case-insensitive)
        if k_lower in self.pref_labels:
            return (self.pref_labels[k_lower], "Rule 1 (Exact Match)")
            
        # Rule 2: Synonym Match (AltLabel)
        if k_lower in self.alt_labels:
            return (self.alt_labels[k_lower], "Rule 2 (Synonym Match)")
            
        # Rule 3: Fuzzy Match (Levenshtein distance <= 2 roughly approx by difflib)
        matches = difflib.get_close_matches(k_lower, self.pref_labels.keys(), n=1, cutoff=0.85)
        if matches:
            return (self.pref_labels[matches[0]], "Rule 3 (Fuzzy Match)")
            
        # Rule 4: Fast Vector Search (Semantic Embedding)
        if self.term_list:
            if self.encoder is None:
                self._init_encoder()
            
            import torch
            from sentence_transformers import util
            
            query_emb = self.encoder.encode(keyword, convert_to_tensor=True)
            cos_scores = util.cos_sim(query_emb, self.term_embeddings)[0]
            top_score, top_idx = torch.topk(cos_scores, k=1)
            
            if top_score.item() > 0.85:
                return (self.term_list[top_idx.item()], "Rule 4 (Semantic Embedding)")

        # Rule 5: LLM Fallback
        llm_mapped = self._call_llm_fallback(keyword)
        if llm_mapped and llm_mapped != "UNMAPPED":
            return (llm_mapped, "Rule 5 (LLM Fallback)")
            
        # Rule 6: Unmapped
        return ("UNMAPPED", "Rule 6 (Unmapped)")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), "../kg.env")
    load_dotenv(env_path)
    
    thesaurus_path = os.path.join(os.path.dirname(__file__), "../ieee-thesaurus.ttl")
    engine = TaxonomyEngine(thesaurus_path)
    
    test_keywords = ["machine learning", "deep learning models", "computational logic", "nonexistent weird tech"]
    for kw in test_keywords:
        mapped, rule = engine.map_keyword(kw)
        print(f"Keyword: '{kw}' -> Mapped: '{mapped}' (via {rule})")
