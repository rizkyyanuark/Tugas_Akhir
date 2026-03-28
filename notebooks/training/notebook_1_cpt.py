"""
=============================================================================
KAGGLE NOTEBOOK 1 — CONTINUED PRETRAINING (CPT)
Ontology-Aware Cross-Lingual TLDR Model
=============================================================================
Environment: Kaggle T4 x2 (32GB VRAM Total)
Base Model:  Qwen/Qwen2.5-0.5B-Instruct
Data:        armanc/scientific_papers (arXiv, 50k abstracts)
Objective:   Domain adaptation ke bahasa ilmiah via next-token prediction
Referensi:   https://huggingface.co/tcy93/scitldr-qwen2.5-0.5b-summarizer
=============================================================================
Salin setiap CELL ke notebook Kaggle. Pastikan GPU T4 x2 aktif.
"""

# =============================================================================
# CELL 1: INSTALL DEPENDENCIES
# =============================================================================
# !pip install -q transformers peft trl bitsandbytes accelerate datasets rouge-score evaluate torch

# =============================================================================
# CELL 2: LOAD BASE MODEL + QLoRA CONFIG
# =============================================================================
import os
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

os.environ["CUDA_VISIBLE_DEVICES"] = "0"

MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"

# QLoRA 4-bit quantization config
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
)

print("📥 Loading base model...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config,
    device_map={"":0},  # Pin ke 1 GPU (0.5B cukup kecil)
    trust_remote_code=True,
)

# LoRA adapter config (sesuai PRD)
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    task_type="CAUSAL_LM",
)

# Pastikan pad_token ada (Qwen tidak punya default)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

model = prepare_model_for_kbit_training(model)
model = get_peft_model(model, lora_config)

trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
total_params = sum(p.numel() for p in model.parameters())
print(f"✅ Model loaded! Trainable: {trainable_params:,} ({trainable_params/total_params*100:.2f}%)")
print(f"📊 GPUs detected: {torch.cuda.device_count()}")


# =============================================================================
# CELL 3: LOAD & PREPROCESS arXiv 50k ABSTRACTS
# =============================================================================
from datasets import load_dataset

print("📥 Loading arXiv abstracts from ccdv/arxiv-summarization...")
raw_dataset = load_dataset("ccdv/arxiv-summarization", split="train")
print(f"   Total available: {len(raw_dataset)} papers")

# Ambil 50k subset (sesuai PRD)
CPT_SIZE = 50_000
cpt_dataset = raw_dataset.shuffle(seed=42).select(range(min(CPT_SIZE, len(raw_dataset))))

def preprocess_cpt(example):
    """Minimal cleaning untuk CPT: plain next-token prediction."""
    text = example["abstract"].strip()
    # Bersihkan arXiv tokens yang tidak berguna
    text = text.replace("\n", " ").strip()
    # Tokenize dengan padding agar semua sequence sama panjang
    tokenized = tokenizer(
        text,
        max_length=512,
        truncation=True,
        padding="max_length",
    )
    tokenized["labels"] = tokenized["input_ids"].copy()
    return tokenized

print("🔄 Tokenizing 50k abstracts...")
tokenized_cpt = cpt_dataset.map(
    preprocess_cpt,
    remove_columns=cpt_dataset.column_names,
    num_proc=2,
    desc="Tokenizing CPT data"
)

# Split train/eval (95/5)
split = tokenized_cpt.train_test_split(test_size=0.05, seed=42)
train_dataset = split["train"]
eval_dataset = split["test"]
print(f"✅ Train: {len(train_dataset)} | Eval: {len(eval_dataset)}")


# =============================================================================
# CELL 4: SETUP TRAINER (CPT, LM OBJECTIVE)
# =============================================================================
from transformers import TrainingArguments, Trainer, DataCollatorForLanguageModeling

training_args = TrainingArguments(
    output_dir="./cpt_checkpoint",
    
    # Hyperparameters sesuai PRD
    learning_rate=1e-4,
    num_train_epochs=1,
    per_device_train_batch_size=2,
    per_device_eval_batch_size=2,
    gradient_accumulation_steps=8,  # Effective batch = 2 * 2_gpu * 8 = 32
    
    # Scheduler
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    
    # Precision
    fp16=True,
    bf16=False,  # T4 tidak support native bf16, pakai fp16
    
    # Logging & Saving (HARUS SAMA strateginya!)
    logging_steps=50,
    eval_strategy="epoch",
    save_strategy="epoch",
    save_total_limit=2,
    load_best_model_at_end=True,
    metric_for_best_model="eval_loss",
    
    # Misc
    report_to="none",
    dataloader_pin_memory=True,
    remove_unused_columns=False,
)

data_collator = DataCollatorForLanguageModeling(
    tokenizer=tokenizer,
    mlm=False,  # Causal LM, bukan masked LM
    pad_to_multiple_of=8,  # Padding alignment untuk efisiensi GPU
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
    data_collator=data_collator,
    processing_class=tokenizer,  # Versi baru transformers
)

print(f"✅ Trainer ready!")
print(f"   Effective batch size: {training_args.per_device_train_batch_size * 2 * training_args.gradient_accumulation_steps}")
print(f"   Total training steps: {len(train_dataset) // (training_args.per_device_train_batch_size * 2 * training_args.gradient_accumulation_steps)}")


# =============================================================================
# CELL 5: TRAIN! + VRAM TRACKING
# =============================================================================
print("🚀 Starting Continued Pretraining (CPT)...")
print("   Estimasi waktu: ~8-10 jam (Kaggle T4 x2)")
print("   Model sedang belajar bahasa ilmiah dari 50k abstrak arXiv...")
print("="*60)

train_result = trainer.train()

# VRAM Peak Tracking (dari referensi Unsloth)
peak_mem = torch.cuda.max_memory_reserved() / 1e9
max_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
print(f"\n📊 Training selesai!")
print(f"   Train Loss:     {train_result.training_loss:.4f}")
print(f"   Peak GPU VRAM:  {peak_mem:.2f} GB")
print(f"   Max GPU VRAM:   {max_mem:.2f} GB")
print(f"   VRAM Usage:     {peak_mem/max_mem*100:.1f}%")


# =============================================================================
# CELL 6: SAVE CPT CHECKPOINT → KAGGLE OUTPUT
# =============================================================================
import shutil

CPT_OUTPUT = "./cpt_checkpoint_final"
print(f"\n💾 Saving CPT checkpoint to {CPT_OUTPUT}...")

# Simpan adapter LoRA + tokenizer
model.save_pretrained(CPT_OUTPUT)
tokenizer.save_pretrained(CPT_OUTPUT)

# Evaluasi perplexity
eval_results = trainer.evaluate()
perplexity = torch.exp(torch.tensor(eval_results["eval_loss"])).item()
print(f"\n📊 CPT Evaluation:")
print(f"   Eval Loss:    {eval_results['eval_loss']:.4f}")
print(f"   Perplexity:   {perplexity:.2f}")
print(f"\n✅ CPT SELESAI! Checkpoint tersimpan di: {CPT_OUTPUT}")
print("   Lanjutkan ke Notebook 2 (SFT) untuk fine-tuning ontologi.")
