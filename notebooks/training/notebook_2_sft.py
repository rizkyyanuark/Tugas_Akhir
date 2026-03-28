"""
=============================================================================
KAGGLE NOTEBOOK 2 — SUPERVISED FINE-TUNING (SFT)
Ontology-Aware Cross-Lingual TLDR Model
=============================================================================
Environment: Kaggle T4 x2 (32GB VRAM Total)
Base:        CPT Checkpoint dari Notebook 1
Data:        Golden Dataset (abstrak ID+EN → TLDR EN 2-kalimat ontologi)
Objective:   Ajarkan model behavior 2-kalimat ontologi-aware TLDR
Referensi:   https://huggingface.co/tcy93/scitldr-qwen2.5-0.5b-summarizer
=============================================================================
Salin setiap CELL ke notebook Kaggle. Pastikan GPU T4 x2 aktif.
Upload golden_tldr_dataset.jsonl ke Kaggle Dataset sebelum mulai.
"""

# =============================================================================
# CELL 1: INSTALL DEPENDENCIES
# =============================================================================
# !pip install -q transformers peft trl bitsandbytes accelerate datasets rouge-score evaluate torch

# =============================================================================
# CELL 2: LOAD CPT CHECKPOINT + QLoRA
# =============================================================================
import os
import json
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from peft import PeftModel, LoraConfig, get_peft_model, prepare_model_for_kbit_training

os.environ["CUDA_VISIBLE_DEVICES"] = "0,1"

# Path ke CPT checkpoint (output Notebook 1)
# Ganti path jika Anda menyimpannya di Kaggle Dataset
CPT_CHECKPOINT = "/kaggle/input/cpt-checkpoint/cpt_checkpoint_final"
# Fallback ke base model jika CPT belum jalan
BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
)

print("📥 Loading model...")
try:
    # Coba load dari CPT checkpoint dulu
    tokenizer = AutoTokenizer.from_pretrained(CPT_CHECKPOINT, trust_remote_code=True)
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base_model, CPT_CHECKPOINT)
    model = model.merge_and_unload()  # Merge CPT adapter
    print("✅ CPT checkpoint loaded & merged!")
except Exception as e:
    print(f"⚠️ CPT checkpoint not found ({e}), loading base model...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    print("✅ Base model loaded (tanpa CPT)")

# Apply fresh LoRA adapter for SFT
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    task_type="CAUSAL_LM",
)

model = prepare_model_for_kbit_training(model)
model = get_peft_model(model, lora_config)

trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
total = sum(p.numel() for p in model.parameters())
print(f"📊 Trainable: {trainable:,} ({trainable/total*100:.2f}%)")

# Pastikan pad_token ada
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token


# =============================================================================
# CELL 3: LOAD & PREPROCESS GOLDEN DATASET
# =============================================================================
from datasets import Dataset

# Path ke golden dataset (upload ke Kaggle Dataset)
GOLDEN_DATASET_PATH = "/kaggle/input/golden-dataset/golden_tldr_dataset.jsonl"
# Fallback: coba path lokal
if not os.path.exists(GOLDEN_DATASET_PATH):
    GOLDEN_DATASET_PATH = "golden_tldr_dataset.jsonl"

print(f"📥 Loading golden dataset from {GOLDEN_DATASET_PATH}...")
records = []
with open(GOLDEN_DATASET_PATH, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            rec = json.loads(line.strip())
            # Filter: hanya ambil yang punya abstract DAN tldr valid
            if rec.get('abstract_text') and rec.get('tldr_text') and len(rec['tldr_text']) > 20:
                records.append(rec)
        except:
            pass

print(f"   Total valid records: {len(records)}")
print(f"   Language distribution:")
id_count = sum(1 for r in records if r.get('abstract_lang') == 'id')
print(f"      🇮🇩 Indonesian: {id_count}")
print(f"      🇬🇧 English:    {len(records) - id_count}")

# Quality stats
print(f"   Ontology quality:")
print(f"      2-sentence: {sum(1 for r in records if r.get('is_2_sentences'))}/{len(records)}")
print(f"      Has problem: {sum(1 for r in records if r.get('has_problem'))}/{len(records)}")
print(f"      Has method:  {sum(1 for r in records if r.get('has_method'))}/{len(records)}")
print(f"      Has results: {sum(1 for r in records if r.get('has_results'))}/{len(records)}")

dataset = Dataset.from_list(records)


# =============================================================================
# CELL 4: FORMAT KE CHAT TEMPLATE + train_on_responses_only
# =============================================================================

# System prompt IDENTIK dengan production (enricher.py)
SFT_SYSTEM_PROMPT = (
    "You are a scientific TLDR assistant for an ontology-based "
    "Knowledge Graph system. Given an academic abstract (which may be "
    "in English or Indonesian), write exactly 2 sentences in English:\n"
    "- Sentence 1: clearly describe the research problem and task.\n"
    "- Sentence 2: describe the proposed method/model, dataset used, "
    "and key results or innovation.\n"
    "Be concise, explicit, and use academic language."
)

def format_sft_example(example):
    """Format golden data ke Qwen chat template."""
    messages = [
        {"role": "system",    "content": SFT_SYSTEM_PROMPT},
        {"role": "user",      "content": f"Abstract:\n{example['abstract_text']}"},
        {"role": "assistant", "content": example['tldr_text']},
    ]
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False
    )
    example["text"] = text
    return example

print("🔄 Formatting dataset ke chat template...")
formatted_dataset = dataset.map(format_sft_example, desc="Formatting SFT data")

# Train/Test split (90/10)
split = formatted_dataset.train_test_split(test_size=0.1, seed=42)
train_dataset = split["train"]
eval_dataset = split["test"]
print(f"✅ Train: {len(train_dataset)} | Test: {len(eval_dataset)}")

# Sample preview
print("\n📋 Sample formatted text (first 500 chars):")
print(train_dataset[0]["text"][:500])


# =============================================================================
# CELL 5: SETUP SFT TRAINER (train_on_responses_only)
# =============================================================================
from transformers import TrainingArguments
from trl import SFTTrainer, DataCollatorForCompletionOnlyLM

# Response template: model hanya belajar dari bagian assistant (TLDR)
response_template = "<|im_start|>assistant\n"
collator = DataCollatorForCompletionOnlyLM(
    response_template=response_template,
    tokenizer=tokenizer,
)

sft_training_args = TrainingArguments(
    output_dir="./sft_checkpoint",
    
    # Hyperparameters sesuai PRD
    learning_rate=2e-4,
    num_train_epochs=3,
    per_device_train_batch_size=2,
    per_device_eval_batch_size=2,
    gradient_accumulation_steps=8,  # Effective batch = 32
    
    # Scheduler
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    
    # Precision
    bf16=True,
    fp16=False,
    
    # Logging & Saving
    logging_steps=10,
    eval_strategy="steps",
    eval_steps=100,
    save_strategy="epoch",
    save_total_limit=2,
    load_best_model_at_end=True,
    metric_for_best_model="eval_loss",
    
    # Misc
    report_to="none",
    max_seq_length=512,
)

trainer = SFTTrainer(
    model=model,
    args=sft_training_args,
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
    data_collator=collator,
    tokenizer=tokenizer,
    dataset_text_field="text",
    max_seq_length=512,
)

print(f"✅ SFT Trainer ready!")
print(f"   Epochs: {sft_training_args.num_train_epochs}")
print(f"   Effective batch: {sft_training_args.per_device_train_batch_size * 2 * sft_training_args.gradient_accumulation_steps}")
print(f"   train_on_responses_only: ✅ (loss hanya di TLDR, bukan instruksi)")


# =============================================================================
# CELL 6: TRAIN!
# =============================================================================
print("🚀 Starting SFT Training...")
print("   Estimasi waktu: ~1-2 jam (Kaggle T4 x2)")
print("="*60)

train_result = trainer.train()

# VRAM Peak Tracking
peak_mem = torch.cuda.max_memory_reserved() / 1e9
max_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
print(f"\n📊 SFT Training selesai!")
print(f"   Train Loss:     {train_result.training_loss:.4f}")
print(f"   Peak GPU VRAM:  {peak_mem:.2f} GB")
print(f"   VRAM Usage:     {peak_mem/max_mem*100:.1f}%")


# =============================================================================
# CELL 7: EVALUASI — ROUGE + ONTOLOGY SLOT COVERAGE
# =============================================================================
from rouge_score import rouge_scorer
import re

print("\n📊 EVALUASI MODEL PADA TEST SET")
print("="*60)

scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)

predictions = []
references = []
slot_stats = {"2_sent": 0, "problem": 0, "method": 0, "dataset": 0, "results": 0, "english": 0}
eval_samples = min(50, len(eval_dataset))

for i in range(eval_samples):
    example = eval_dataset[i]
    abstract = example["abstract_text"]
    reference_tldr = example["tldr_text"]
    
    # Generate prediction
    messages = [
        {"role": "system", "content": SFT_SYSTEM_PROMPT},
        {"role": "user",   "content": f"Abstract:\n{abstract}"},
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=128,
            do_sample=False,
            repetition_penalty=1.1,
        )
    
    pred = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    
    predictions.append(pred)
    references.append(reference_tldr)
    
    # Ontology slot coverage check
    pred_lower = pred.lower()
    sentences = [s.strip() for s in pred.split('.') if s.strip()]
    slot_stats["2_sent"] += int(len(sentences) == 2)
    slot_stats["problem"] += int(any(w in pred_lower for w in ['address', 'tackle', 'develop', 'implement', 'propose', 'problem']))
    slot_stats["method"] += int(any(w in pred_lower for w in ['method', 'algorithm', 'model', 'approach', 'technique', 'using']))
    slot_stats["dataset"] += int(any(w in pred_lower for w in ['dataset', 'data', 'sample', 'respondent', 'corpus']))
    slot_stats["results"] += int(any(w in pred_lower for w in ['achiev', 'result', 'performance', 'accuracy', '%', 'score']))
    
    # English check (no Indonesian keywords)
    is_english = not any(w in pred_lower for w in ['penelitian', 'menggunakan', 'bertujuan', 'metode', 'menunjukkan'])
    slot_stats["english"] += int(is_english)

# ROUGE Scores
r1, r2, rl = [], [], []
for pred, ref in zip(predictions, references):
    scores = scorer.score(ref, pred)
    r1.append(scores['rouge1'].fmeasure)
    r2.append(scores['rouge2'].fmeasure)
    rl.append(scores['rougeL'].fmeasure)

print(f"\n--- ROUGE Scores (pada {eval_samples} samples) ---")
print(f"ROUGE-1: {sum(r1)/len(r1):.4f}")
print(f"ROUGE-2: {sum(r2)/len(r2):.4f}")
print(f"ROUGE-L: {sum(rl)/len(rl):.4f}")

print(f"\n--- Ontology Slot Coverage ---")
for k, v in slot_stats.items():
    pct = v / eval_samples * 100
    label = k.replace("_", " ").title()
    emoji = "✅" if pct >= 80 else "⚠️" if pct >= 50 else "❌"
    print(f"{emoji} {label}: {v}/{eval_samples} ({pct:.1f}%)")

# Show 3 sample predictions
print(f"\n--- Sample Predictions ---")
for i in range(min(3, len(predictions))):
    print(f"\n[{i+1}] Abstract: {eval_dataset[i]['abstract_text'][:150]}...")
    print(f"    Reference: {references[i][:150]}...")
    print(f"    Predicted: {predictions[i][:150]}...")


# =============================================================================
# CELL 8: SAVE FINAL MODEL → PUSH TO HUGGINGFACE HUB
# =============================================================================

FINAL_MODEL_DIR = "./tldr-ontology-qwen-0.5b"
print(f"\n💾 Saving final model to {FINAL_MODEL_DIR}...")

model.save_pretrained(FINAL_MODEL_DIR)
tokenizer.save_pretrained(FINAL_MODEL_DIR)
print(f"✅ Adapter saved!")

# Optional: Push to HuggingFace Hub
try:
    from huggingface_hub import notebook_login
    print("\n🤗 Login ke HuggingFace Hub untuk upload model...")
    notebook_login()
    
    HF_REPO = "rizkyyanuark/tldr-ontology-qwen-0.5b"
    model.push_to_hub(HF_REPO)
    tokenizer.push_to_hub(HF_REPO)
    print(f"✅ Model berhasil di-push ke: https://huggingface.co/{HF_REPO}")
except Exception as e:
    print(f"⚠️ Push to Hub gagal: {e}")
    print(f"   Model tersimpan secara lokal di: {FINAL_MODEL_DIR}")

print("\n" + "="*60)
print("🎉 TRAINING PIPELINE SELESAI!")
print(f"   Model siap di-deploy ke Modal.com atau diintegrasikan ke enricher.py")
print("="*60)
