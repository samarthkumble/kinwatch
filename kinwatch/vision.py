"""Vision step: turn a Ring snapshot into a structured, caregiver-friendly label.

Ring's history API labels Playground events only as "on_demand" with no CV
detections, so KinWatch looks at the frame itself. Backends
(KINWATCH_VISION_BACKEND):

  bedrock      Amazon Bedrock multimodal model (Nova 2 Lite). Best descriptions.
               Auth: AWS_BEARER_TOKEN_BEDROCK (Bedrock API key) or AWS credentials.
  rekognition  Amazon Rekognition DetectLabels. Auth: AWS access keys.
  auto         (default) bedrock, and if the account refuses it, rekognition.

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

MODEL_ID = os.environ.get("KINWATCH_VISION_MODEL", "us.amazon.nova-2-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
CACHE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "vision"
LABELS = ("person", "package", "vehicle", "animal", "nothing")
BACKEND = os.environ.get("KINWATCH_VISION_BACKEND", "auto").lower()

# Rekognition label names -> KinWatch label, checked in priority order
# (a person outranks a package, which outranks a vehicle, ...).
REKOGNITION_MAP = [
    ("person", {"Person", "Human", "Adult", "Man", "Woman", "Child", "Male", "Female",
                "Boy", "Girl", "Senior Citizen", "Face"}),
    ("package", {"Box", "Cardboard", "Carton", "Package", "Package Delivery", "Parcel",
                 "Package Delivery Box"}),
    ("vehicle", {"Car", "Vehicle", "Truck", "Van", "Automobile", "Motorcycle", "Scooter",
                 "Bicycle", "Bus", "Moped"}),
    ("animal", {"Animal", "Bird", "Dog", "Cat", "Pet", "Wildlife", "Mammal", "Cow",
                "Monkey", "Squirrel"}),
]
SENTENCE = {
    "person": "Someone is at the front door.",
    "package": "A package has been left at the front door.",
    "vehicle": "A vehicle is outside the house.",
    "animal": "An animal is near the front door ({what}).",
    "nothing": "Something moved, but nothing important is in view.",
}
# Errors that mean "this account can't use Bedrock", so auto mode moves on.
_REFUSED = ("Operation not allowed", "AccessDenied", "currently being verified",
            "not authorized", "don't have access")

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
                 client=None, rekognition_client=None, backend: str | None = None):
        # live: call AWS (and cache); replay: cache only, never call AWS
        self.mode = (mode or os.environ.get("KINWATCH_VISION", "live")).lower()
        # read at creation time, not import time, so changing the env var takes effect
        self.backend = (backend or os.environ.get("KINWATCH_VISION_BACKEND", "auto")).lower()
        self.cache_dir = Path(cache_dir or CACHE_DIR)
        self._client = client
        self._rek = rekognition_client
        self._bedrock_refused = False

    def _bedrock(self):
        if self._client is None:
            import boto3  # imported lazily so replay works without boto3 configured
            self._client = boto3.client("bedrock-runtime", region_name=REGION)
        return self._client

    def _describe_bedrock(self, image_path: Path, data: bytes) -> VisionResult:
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
        return VisionResult(**parse_model_json(text), model=MODEL_ID)

    def _rekognition_client(self):
        if self._rek is None:
            import boto3
            self._rek = boto3.client("rekognition", region_name=REGION)
        return self._rek

    def _describe_rekognition(self, data: bytes) -> VisionResult:
        resp = self._rekognition_client().detect_labels(
            Image={"Bytes": data}, MaxLabels=30, MinConfidence=55)
        return rekognition_to_result(resp.get("Labels", []))

    def describe(self, image_path: str | Path) -> VisionResult | None:
        image_path = Path(image_path)
        data = image_path.read_bytes()
        cache_file = self.cache_dir / f"{_sha256(data)}.json"
        if cache_file.exists():
            return VisionResult(**{**json.loads(cache_file.read_text()), "cached": True})
        if self.mode == "replay":
            return None

        result = None
        if self.backend in ("bedrock", "auto") and not self._bedrock_refused:
            try:
                result = self._describe_bedrock(image_path, data)
            except Exception as exc:
                if self.backend == "bedrock" or not any(m in str(exc) for m in _REFUSED):
                    raise
                self._bedrock_refused = True      # remember for the rest of the run
                print(f"      (Bedrock refused this account: {str(exc)[:80]}; "
                      "using Amazon Rekognition)")
        if result is None:
            result = self._describe_rekognition(data)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = asdict(result)
        payload.pop("cached")
        cache_file.write_text(json.dumps(payload, indent=2))
        return result


# Too generic to tell a family anything.
GENERIC = {"Outdoors", "Nature", "Weather", "Indoors", "Architecture", "Building", "Housing",
           "House", "Plant", "Tree", "Sky", "Daylight", "Night", "Photography", "City",
           "Urban", "Road", "Ground", "Land", "Scenery", "Landscape", "Home Decor"}
MATCH_MIN = 60     # a KinWatch label needs at least this confidence
EXTRA_MIN = 80     # "Also in view" details need more (skips guesses like "Hot Tub 62%")


def rekognition_to_result(labels: list[dict]) -> VisionResult:
    """Turn Rekognition DetectLabels output into a KinWatch label + sentence."""
    labels = sorted(labels, key=lambda l: -l.get("Confidence", 0))
    strong = [l for l in labels if l.get("Confidence", 0) >= MATCH_MIN]
    names = [l["Name"] for l in strong]
    parents = {p["Name"] for l in strong for p in l.get("Parents", [])}
    seen = set(names) | parents
    label = "nothing"
    for kw_label, words in REKOGNITION_MAP:
        if seen & words:
            label = kw_label
            break
    animal = next((n for n in names if n in REKOGNITION_MAP[3][1] - {"Animal", "Mammal",
                                                                       "Wildlife", "Pet"}), "animal")
    sentence = SENTENCE[label].format(what=animal.lower())
    mapped = set().union(*(w for _, w in REKOGNITION_MAP))
    extras = [l["Name"].lower() for l in labels
              if l.get("Confidence", 0) >= EXTRA_MIN
              and l["Name"] not in mapped and l["Name"] not in GENERIC][:3]
    if extras:
        sentence += " Also in view: " + ", ".join(extras) + "."
    return VisionResult(
        label=label, description=sentence,
        person_visible=label == "person",
        package_visible=bool(seen & REKOGNITION_MAP[1][1]),
        concern=False, model="amazon-rekognition-detectlabels")


if __name__ == "__main__":  # python -m kinwatch.vision snapshots/xyz.jpg
    import sys
    for p in sys.argv[1:]:
        r = Vision().describe(p)
        print(p, "->", json.dumps(asdict(r), indent=2) if r else "no cached result")
