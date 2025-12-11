import os
import json
import random
import glob
from pathlib import Path
from typing import List, Dict

import torch
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments

# --- Configuration ---
BASE_DIR = Path("/app")
DATA_DIR = BASE_DIR / "data"
JOURNALS_DIR = DATA_DIR / "journals"
MODEL_OUTPUT_DIR = DATA_DIR / "models" / "adapter"

# Hyperparameters
MAX_SEQ_LENGTH = 2048
DTYPE = None # Auto detection
LOAD_IN_4BIT = True
TARGET_MODEL = "unsloth/llama-3-8b-bnb-4bit"

class TrainerManager:
    def __init__(self):
        self.model, self.tokenizer = FastLanguageModel.from_pretrained(
            model_name=TARGET_MODEL,
            max_seq_length=MAX_SEQ_LENGTH,
            dtype=DTYPE,
            load_in_4bit=LOAD_IN_4BIT,
        )
        
        self.model = FastLanguageModel.get_peft_model(
            self.model,
            r=16,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                            "gate_proj", "up_proj", "down_proj"],
            lora_alpha=16,
            lora_dropout=0,
            bias="none",
            use_gradient_checkpointing=True, 
            random_state=3407,
        )

    def prepare_dataset(self) -> List[Dict]:
        """
        Reads Markdown journals and converts them to Instruction Tuning format.
        Replay Buffer Logic:
        - 80% Recent (Last 7 days)
        - 20% Random History
        """
        all_files = sorted(list(JOURNALS_DIR.glob("*_daily.md")), reverse=True)
        if not all_files:
            return []

        # Recent vs Old
        recent_files = all_files[:7]
        old_files = all_files[7:]
        
        selected_files = recent_files[:]
        
        # Add Replay Data (20% of total set size)
        if old_files:
            target_replay_count = max(1, int(len(recent_files) * 0.25))
            replay_files = random.sample(old_files, min(len(old_files), target_replay_count))
            selected_files.extend(replay_files)
            
        dataset = []
        for p in selected_files:
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
                # Naive parsing: The content IS the response. 
                # Prompt: "What did I do on {date}?"
                # Extract date from filename
                date_str = p.name.split("_daily")[0]
                
                entry = {
                    "instruction": f"Summarize my activities on {date_str}.",
                    "input": "",
                    "output": content # The full daily summary
                }
                dataset.append(entry)
                
        return dataset

    def train(self):
        data = self.prepare_dataset()
        if not data:
            print("No training data found.")
            return

        print(f"Starting training with {len(data)} samples...")
        
        # Convert list of dicts to HuggingFace Dataset
        from datasets import Dataset
        hf_dataset = Dataset.from_list(data)

        trainer = SFTTrainer(
            model=self.model,
            tokenizer=self.tokenizer,
            train_dataset=hf_dataset,
            dataset_text_field="text",
            max_seq_length=MAX_SEQ_LENGTH,
            dataset_num_proc=2,
            packing=False,
            args=TrainingArguments(
                per_device_train_batch_size=2,
                gradient_accumulation_steps=4,
                warmup_steps=5,
                max_steps=60, # Small steps for daily incremental training
                learning_rate=2e-4,
                fp16=not torch.cuda.is_bf16_supported(),
                bf16=torch.cuda.is_bf16_supported(),
                logging_steps=1,
                optim="adamw_8bit",
                weight_decay=0.01,
                lr_scheduler_type="linear",
                seed=3407,
                output_dir="outputs",
            ),
        )
        
        trainer.train()
        
        # Save Adapter
        print(f"Saving adapter to {MODEL_OUTPUT_DIR}")
        self.model.save_pretrained(MODEL_OUTPUT_DIR)
        self.tokenizer.save_pretrained(MODEL_OUTPUT_DIR)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="Stay alive and wait for signal (not implemented in MVP)")
    args = parser.parse_args()
    
    # Simple MVP: Run once and exit
    manager = TrainerManager()
    manager.train()
