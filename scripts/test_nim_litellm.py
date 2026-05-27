"""Quick smoke test for NVIDIA NIM via LiteLLM."""

import argparse
import os

from dotenv import load_dotenv
from litellm import completion


DEFAULT_MODEL = "nvidia_nim/meta/llama-3.1-70b-instruct"
DEFAULT_PROMPT = "Reply with exactly: NIM OK"


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Test NVIDIA NIM model via LiteLLM")
    parser.add_argument("--model", type=str, default=os.getenv("AGENT_LLM", DEFAULT_MODEL))
    parser.add_argument("--prompt", type=str, default=DEFAULT_PROMPT)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()

    if not os.getenv("NVIDIA_NIM_API_KEY"):
        raise RuntimeError("Missing NVIDIA_NIM_API_KEY")

    response = completion(
        model=args.model,
        messages=[{"role": "user", "content": args.prompt}],
        temperature=args.temperature,
    )
    message = response.choices[0].message.content or ""
    print(message.strip())


if __name__ == "__main__":
    main()
