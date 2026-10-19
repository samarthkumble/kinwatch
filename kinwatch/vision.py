"""Vision step: turn a Ring snapshot into a structured, caregiver-friendly label.

Ring's history API labels Playground events only as "on_demand" with no CV
detections, so KinWatch asks an Amazon Bedrock multimodal model (Nova Lite by
default) what is actually in the frame.

Auth: set AWS_BEARER_TOKEN_BEDROCK (a Bedrock API key) or normal AWS credentials.
Every answer is cached in fixtures/vision/<sha256>.json, so replay mode and the
tests work with no AWS account at all.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

MODEL_ID = os.environ.get("KINWATCH_VISION_MODEL", "us.amazon.nova-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
CACHE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "vision"
LABELS = ("person", "package", "vehicle", "animal", "nothing")

PROMPT = """You are the vision module of KinWatch, a caretaking assistant that watches
the front door of an elderly parent who lives alone. Look at this Ring camera frame.

Reply with ONLY a JSON object, no other text:
{
  "label": one of "person", "package", "vehicle", "animal", "nothing"
           (the most important thing for a caregiver; a person outranks a package),
  "description": one short sentence a worried family member can read on a phone,
  "person_visible": true/false,
  "package_visible": true/false,
  "concern": true if this needs the family's attention, otherwise false
}"""


@dataclass
class VisionResult:
    label: str
    description: str
    person_visible: bool
    package_visible: bool
    concern: bool
    model: str = MODEL_ID
    cached: bool = False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_model_json(text: str) -> dict:
    """Pull the first JSON object out of the model's reply (models sometimes
    wrap it in ```json fences or add a sentence)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON in model reply: {text[:200]!r}")
    data = json.loads(match.group(0))
    label = str(data.get("label", "nothing")).lower().strip()
    if label not in LABELS:
        label = "nothing"
    return {
        "label": label,
        "description": str(data.get("description", "")).strip()[:300],
        "person_visible": bool(data.get("person_visible", label == "person")),
        "package_visible": bool(data.get("package_visible", label == "package")),
        "concern": bool(data.get("concern", False)),
    }


class Vision:
    def __init__(self, mode: str | None = None, cache_dir: Path | str | None = None,
                 client=None):
        # live: call Bedrock (and cache); replay: cache only, never call AWS
        self.mode = (mode or os.environ.get("KINWATCH_VISION", "live")).lower()
        self.cache_dir = Path(cache_dir or CACHE_DIR)
        self._client = client

    def _bedrock(self):
        if self._client is None:
            import boto3  # imported lazily so replay works without boto3 configured
            self._client = boto3.client("bedrock-runtime", region_name=REGION)
        return self._client

    def describe(self, image_path: str | Path) -> VisionResult | None:
        image_path = Path(image_path)
        data = image_path.read_bytes()
        cache_file = self.cache_dir / f"{_sha256(data)}.json"
        if cache_file.exists():
            return VisionResult(**{**json.loads(cache_file.read_text()), "cached": True})
        if self.mode == "replay":
            return None

        fmt = "png" if image_path.suffix.lower() == ".png" else "jpeg"
        resp = self._bedrock().converse(
            modelId=MODEL_ID,
            messages=[{"role": "user", "content": [
                {"image": {"format": fmt, "source": {"bytes": data}}},
                {"text": PROMPT},
            ]}],
            inferenceConfig={"maxTokens": 300, "temperature": 0},
        )
        text = "".join(part.get("text", "")
                       for part in resp["output"]["message"]["content"])
        result = VisionResult(**parse_model_json(text), model=MODEL_ID)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = asdict(result)
        payload.pop("cached")
        cache_file.write_text(json.dumps(payload, indent=2))
        return result


if __name__ == "__main__":  # python -m kinwatch.vision snapshots/xyz.jpg
    import sys
    for p in sys.argv[1:]:
        r = Vision().describe(p)
        print(p, "->", json.dumps(asdict(r), indent=2) if r else "no cached result")
