import modal
from pydantic import BaseModel

# --- Setup Modal App & Image ---
app = modal.App("scitldr-api")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("torch", "transformers", "peft", "accelerate", "fastapi[standard]", "pydantic")
)

# --- Define Request Schema ---
class TLDRRequest(BaseModel):
    title: str = ""
    abstract: str
    
class KeywordRequest(BaseModel):
    abstract: str

# --- Define the App Class ---
@app.cls(image=image, gpu="T4", scaledown_window=300)
class SciTLDRModel:
    @modal.enter()
    def load_model(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
        
        print("Loading base model Qwen2.5-0.5B-Instruct...")
        base_model_id = "Qwen/Qwen2.5-0.5B-Instruct"
        adapter_id = "tcy93/scitldr-qwen2.5-0.5b-summarizer"
        
        self.tokenizer = AutoTokenizer.from_pretrained(base_model_id)
        
        # Load base model
        base_model = AutoModelForCausalLM.from_pretrained(
            base_model_id,
            torch_dtype=torch.bfloat16,
            device_map="auto"
        )
        
        # Load adapter
        print(f"Loading adapter {adapter_id}...")
        self.model = PeftModel.from_pretrained(base_model, adapter_id)
        self.model.eval()
        
        # Merge adapter for faster inference
        print("Merging adapter...")
        self.model = self.model.merge_and_unload()
        print("✅ Model loaded successfully!")

    @modal.fastapi_endpoint(method="POST")
    def generate(self, req: TLDRRequest):
        print(f"Generating TLDR for: {req.title[:50]}")
        
        if not req.abstract or len(req.abstract.strip()) < 30:
            return {"tldr": "", "status": "error_abstract_too_short"}
            
        system_prompt = """You are an AI assistant specializing in academic data extraction.
Your Task: Read the following journal abstract and summarize it into EXACTLY 2 SENTENCES in ENGLISH that are very dense and specific.

ONTOLOGY SCHEMA RULES:
[Problem], [Task], [Field], [Method], [Model], [Innovation], [Dataset], [Tool], [Metric].

STRUCTURE:
Sentence 1: Background & Approach (Problem/Task, Field, Method).
Sentence 2: Experiments & Results (Dataset, Tool, Metric).

EXAMPLE:
Abstract: "Penelitian ini bertujuan mendeteksi hoaks pada Twitter menggunakan algoritma BERT. Kami menggunakan dataset ID-Hoax dan mencapai akurasi 95%."
Output: This research addresses hoax detection within the Twitter social media domain using the BERT algorithm. Experiments were conducted on the ID-Hoax dataset and achieved an accuracy of 95%.

STRICT RULES:
- NO pronouns like "this method".
- THE OUTPUT MUST BE IN ENGLISH.
- DO NOT explain what is missing."""

        user_content = f"ORIGINAL ABSTRACT:\n{req.abstract}\n\nOUTPUT 2-SENTENCE TL;DR IN ENGLISH:"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
        
        generated_ids = self.model.generate(
            **model_inputs,
            max_new_tokens=256,
            temperature=1, # Match exact params used in training/scoring
            top_p=1,
            do_sample=False
        )
        
        generated_ids = [
            output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        
        response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return {"tldr": response.strip(), "status": "success"}

    @modal.fastapi_endpoint(method="POST")
    def extract_keywords(self, req: KeywordRequest):
        print("Extracting keywords...")
        
        if not req.abstract or len(req.abstract.strip()) < 30:
            return {"keywords": "", "status": "error_abstract_too_short"}
            
        system_prompt = """You are an AI assistant specializing in academic data extraction.
Your Task: Read the following journal abstract and extract EXACTLY 4 to 5 highly relevant academic keywords.

STRICT RULES:
- Output ONLY the keywords separated by commas.
- Do NOT output any conversational text.
- Do NOT output bullet points or numbers.
- The keywords MUST be in the EXACT same language as the abstract."""

        user_content = f"ABSTRACT:\n{req.abstract}\n\nKEYWORDS:"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
        
        generated_ids = self.model.generate(
            **model_inputs,
            max_new_tokens=50,
            temperature=0.1,
            top_p=1,
            do_sample=False
        )
        
        generated_ids = [
            output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        
        response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        clean_response = response.strip().strip('"').strip("'")
        return {"keywords": clean_response, "status": "success"}

