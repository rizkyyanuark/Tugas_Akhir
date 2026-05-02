import logging
from typing import List, Dict, Any, Tuple
import spacy
from gliner import GLiNER

logger = logging.getLogger(__name__)

class NLPParser:
    def __init__(self, spacy_model="en_core_web_sm", gliner_model="urchade/gliner_small-v2.1"):
        logger.info(f"Loading spaCy model: {spacy_model}")
        try:
            self.nlp = spacy.load(spacy_model)
        except OSError:
            logger.warning(f"spaCy model '{spacy_model}' not found. Downloading...")
            import subprocess
            subprocess.run(["python", "-m", "spacy", "download", spacy_model], check=True)
            self.nlp = spacy.load(spacy_model)
            
        logger.info(f"Loading GLiNER model: {gliner_model}")
        self.gliner = GLiNER.from_pretrained(gliner_model)
        
        # Labels for zero-shot NER in academic domain
        self.labels = [
            "METHOD", 
            "DATASET", 
            "METRIC", 
            "TECHNOLOGY", 
            "APPLICATION_DOMAIN", 
            "ALGORITHM"
        ]

    def _chunk_text(self, text: str) -> List[str]:
        """
        Splits text into sentence chunks using spaCy.
        """
        doc = self.nlp(text)
        return [sent.text.strip() for sent in doc.sents if sent.text.strip()]

    def parse_document(self, tldr: str, abstract: str) -> Tuple[List[str], List[Dict[str, Any]], List[Tuple[str, str]]]:
        """
        Parses a document (preferring tldr over abstract).
        Returns:
            chunks: List of sentence texts.
            entities: List of extracted entities with label.
            co_occurrences: List of (entity1, entity2) pairs appearing in the same sentence.
        """
        # Select best text source
        text_to_parse = tldr if tldr and str(tldr).strip() else abstract
        if not text_to_parse or str(text_to_parse).strip() == "":
            return [], [], []
            
        chunks = self._chunk_text(str(text_to_parse))
        
        all_entities = []
        co_occurrences = []
        
        for chunk in chunks:
            # Predict entities in chunk
            try:
                # GLiNER predict_entities returns: [{'text': '...', 'label': '...', 'score': ...}]
                chunk_entities = self.gliner.predict_entities(chunk, self.labels)
            except Exception as e:
                logger.error(f"GLiNER prediction failed on chunk: {e}")
                chunk_entities = []
                
            # Filter and normalize entities
            valid_entities = []
            for ent in chunk_entities:
                if ent.get('score', 0) > 0.5: # Confidence threshold
                    # Normalize text: lowercased and stripped
                    ent_text = ent['text'].strip().lower()
                    if ent_text:
                        valid_entities.append({
                            "text": ent_text,
                            "label": ent['label'].upper(),
                            "chunk": chunk
                        })
            
            all_entities.extend(valid_entities)
            
            # Extract co-occurrences within this chunk
            ent_texts = list(set([e['text'] for e in valid_entities]))
            for i in range(len(ent_texts)):
                for j in range(i + 1, len(ent_texts)):
                    co_occurrences.append((ent_texts[i], ent_texts[j]))
                    
        return chunks, all_entities, co_occurrences

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = NLPParser()
    
    sample_tldr = "We propose a novel deep learning framework for diabetic retinopathy detection using Vision Transformer. The model achieves 95% accuracy on the APTOS 2019 dataset."
    sample_abstract = ""
    
    chunks, entities, co_occurrences = parser.parse_document(sample_tldr, sample_abstract)
    
    print("\nChunks:")
    for c in chunks: print(f" - {c}")
    
    print("\nEntities:")
    for e in entities: print(f" - {e['text']} [{e['label']}]")
    
    print("\nCo-occurrences:")
    for co in co_occurrences: print(f" - {co[0]} <-> {co[1]}")
