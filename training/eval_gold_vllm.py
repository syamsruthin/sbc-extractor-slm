"""Phase 3: generate gold-set predictions with vLLM + the trained LoRA adapter (CUDA).

    pip install vllm
    python eval_gold_vllm.py --data-dir /kaggle/input/sbc-sft \
        --adapter /kaggle/working/qwen3-4b-sbc-lora/final --run qwen3-4b-lora-r16

Writes <out-dir>/<run>/<plan_id>.json for the 10 gold docs. Copy that folder to
eval/predictions/ in the repo and score it with eval/score.py.

Uses the same student prompt as training (student_prompt.txt in the data dir) and,
unless --no-guided, JSON-schema guided decoding so every output is schema-valid.
This is a first look at Phase 6: vLLM serves the base model and applies the LoRA
adapter per request (no merge needed).
"""

import argparse
import json
import time
from pathlib import Path

from vllm import LLM, SamplingParams
from vllm.lora.request import LoRARequest


def guided_params(schema: dict) -> dict:
    """SamplingParams kwargs for JSON-schema decoding across vLLM versions."""
    try:  # newer vLLM
        from vllm.sampling_params import StructuredOutputsParams
        return {"structured_outputs": StructuredOutputsParams(json=schema)}
    except ImportError:  # older vLLM
        from vllm.sampling_params import GuidedDecodingParams
        return {"guided_decoding": GuidedDecodingParams(json=schema)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--adapter", default=None, help="LoRA adapter dir; omit to run the base model")
    parser.add_argument("--model", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--run", required=True)
    parser.add_argument("--out-dir", default="/kaggle/working/predictions")
    parser.add_argument("--no-guided", action="store_true")
    parser.add_argument("--max-model-len", type=int, default=16384)
    args = parser.parse_args()

    data = Path(args.data_dir)
    system = (data / "student_prompt.txt").read_text().strip()
    schema = json.loads((data / "schema.json").read_text())
    docs = sorted((data / "gold").glob("*.md"))

    llm = LLM(
        model=args.model,
        dtype="half",  # T4 has no bf16
        max_model_len=args.max_model_len,
        gpu_memory_utilization=0.90,
        enable_lora=args.adapter is not None,
        max_lora_rank=64,
    )
    params = SamplingParams(temperature=0.0, max_tokens=6000,
                            **({} if args.no_guided else guided_params(schema)))
    lora = LoRARequest("sbc", 1, args.adapter) if args.adapter else None

    conversations = [[{"role": "system", "content": system},
                      {"role": "user", "content": d.read_text()}] for d in docs]
    start = time.time()
    outputs = llm.chat(conversations, params, lora_request=lora)
    elapsed = time.time() - start

    out = Path(args.out_dir) / args.run
    out.mkdir(parents=True, exist_ok=True)
    gen_tokens = 0
    for doc, o in zip(docs, outputs):
        (out / f"{doc.stem}.json").write_text(o.outputs[0].text)
        gen_tokens += len(o.outputs[0].token_ids)
    stats = {"docs": len(docs), "seconds": round(elapsed, 1), "generated_tokens": gen_tokens,
             "throughput_tok_s": round(gen_tokens / elapsed, 1), "guided": not args.no_guided,
             "adapter": args.adapter}
    (out / "_stats.json").write_text(json.dumps(stats, indent=1))
    print(stats, "->", out)


if __name__ == "__main__":
    main()
