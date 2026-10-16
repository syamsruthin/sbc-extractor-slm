"""Phase 3: QLoRA fine-tuning of Qwen3-4B on the SBC SFT set (CUDA: Kaggle T4 / any NVIDIA GPU).

    pip install -U "trl>=0.20" peft bitsandbytes liger-kernel datasets accelerate
    python train_qlora.py --data-dir /kaggle/input/sbc-sft --max-steps 5      # dry run first
    python train_qlora.py --data-dir /kaggle/input/sbc-sft                    # full run

What each piece does (see docs/07-finetuning.md):
  - BitsAndBytesConfig: frozen base weights stored in 4-bit NF4 with double quantization,
    dequantized per layer to the compute dtype (fp16 on T4, which lacks bf16).
  - LoraConfig: rank-16 adapters on all 7 linear projections; only these get gradients.
  - prompt/completion format + completion_only_loss: loss only on the assistant JSON.
    (Qwen3's chat template has no {% generation %} markers, so TRL's assistant_only_loss
    can't find assistant tokens; splitting into prompt/completion is the robust way.)
  - use_liger_kernel: fused linear + cross-entropy, so the 12k x 152k logits tensor
    (~7.5 GB in fp32) is never materialized.
  - gradient checkpointing + paged 8-bit AdamW: activation and optimizer memory.

Untested on CUDA by the author (developed on a Mac). Do the --max-steps 5 dry run first.
"""

import argparse
import json
from pathlib import Path

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def to_prompt_completion(example: dict) -> dict:
    """messages -> conversational prompt/completion, so loss covers only the completion."""
    msgs = example["messages"]
    assert msgs[-1]["role"] == "assistant"
    return {"prompt": msgs[:-1], "completion": msgs[-1:]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="dir with train.jsonl and valid.jsonl")
    parser.add_argument("--output-dir", default="/kaggle/working/qwen3-4b-sbc-lora")
    parser.add_argument("--model", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--epochs", type=float, default=2)
    parser.add_argument("--max-steps", type=int, default=-1, help="override epochs (dry runs)")
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=int, default=32)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=12288)
    parser.add_argument("--eval-docs", type=int, default=16, help="validation subset size (eval is slow)")
    parser.add_argument("--eval-steps", type=int, default=20)
    args = parser.parse_args()

    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    compute_dtype = torch.bfloat16 if bf16 else torch.float16
    print(f"GPU: {torch.cuda.get_device_name(0)} | compute dtype: {compute_dtype}")

    data = load_dataset("json", data_files={
        "train": str(Path(args.data_dir) / "train.jsonl"),
        "validation": str(Path(args.data_dir) / "valid.jsonl"),
    })
    data = data.map(to_prompt_completion, remove_columns=["messages"])
    eval_set = data["validation"].select(range(min(args.eval_docs, len(data["validation"]))))

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=compute_dtype,
        ),
        torch_dtype=compute_dtype,
        attn_implementation="sdpa",  # memory-efficient attention kernel; works on T4
        device_map={"": 0},
    )
    print(f"base model memory: {torch.cuda.memory_allocated() / 2**30:.2f} GiB")

    peft_config = LoraConfig(
        r=args.rank, lora_alpha=args.alpha, lora_dropout=0.05,
        target_modules=TARGETS, bias="none", task_type="CAUSAL_LM",
    )
    config = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        optim="paged_adamw_8bit",
        max_length=args.max_length,
        packing=False,
        completion_only_loss=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        use_liger_kernel=True,
        bf16=bf16,
        fp16=not bf16,
        logging_steps=5,
        eval_strategy="steps",
        eval_steps=args.eval_steps,
        save_strategy="steps",
        save_steps=args.eval_steps,
        save_total_limit=3,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        report_to="none",
    )
    trainer = SFTTrainer(
        model=model,
        args=config,
        train_dataset=data["train"],
        eval_dataset=eval_set,
        processing_class=tokenizer,
        peft_config=peft_config,
    )
    trainer.model.print_trainable_parameters()
    trainer.train()

    final = Path(args.output_dir) / "final"
    trainer.save_model(str(final))  # LoRA adapter only (~130 MB), not the base model
    tokenizer.save_pretrained(str(final))
    history = [h for h in trainer.state.log_history if "loss" in h or "eval_loss" in h]
    (final / "log_history.json").write_text(json.dumps(history, indent=1))
    print(f"peak GPU memory: {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB | adapter -> {final}")


if __name__ == "__main__":
    main()
