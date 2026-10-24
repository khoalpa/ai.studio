from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from ..errors import RuntimeUnavailableError
from ..hashing import canonical_json_bytes, sha256_bytes


@dataclass(frozen=True)
class ControlMap:
    data: bytes
    evidence: dict[str, Any]


class DepthControlMapProvider:
    """Build a shot-bound composition canvas and estimate its DPT depth map."""

    def __init__(self, settings: dict[str, Any]) -> None:
        config = (settings.get("control_preprocessors") or {}).get("depth") or {}
        self.model_id = str(config.get("model") or "")
        self.device = str(config.get("device") or "cpu")
        self.conditioning_scale = float(config.get("conditioning_scale", 0.8))
        self.local_files_only = bool(settings.get("local_files_only", False))
        self._processor = None
        self._model = None
        self._cache: dict[str, ControlMap] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.model_id)

    def create(
        self,
        *,
        shot: dict[str, Any],
        reference_inputs: list[dict[str, Any]],
        size: tuple[int, int],
    ) -> ControlMap:
        cache_key = sha256_bytes(canonical_json_bytes({
            "shot": {
                "subjects": shot.get("subjects", []),
                "prop_layout": shot.get("prop_layout", []),
                "composition": shot.get("composition", {}),
            },
            "references": [
                {
                    "reference_id": item.get("reference_id"),
                    "sha256": sha256_bytes(item["data"]),
                }
                for item in reference_inputs
            ],
            "size": list(size),
            "model_id": self.model_id,
        }))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        canvas = composition_canvas(shot, reference_inputs, size)
        depth = self._estimate(canvas)
        output = io.BytesIO()
        depth.save(output, format="PNG", optimize=True)
        data = output.getvalue()
        result = ControlMap(
            data=data,
            evidence={
                "schema_version": "1.0",
                "control_type": "depth",
                "method": "DPT_FROM_SHOT_COMPOSITION_V1",
                "model_id": self.model_id,
                "control_map_sha256": sha256_bytes(data),
                "width": size[0],
                "height": size[1],
                "conditioning_scale": self.conditioning_scale,
                "reference_count": len(reference_inputs),
                "source": "SHOT_SPEC_AND_CHARACTER_REFERENCES",
            },
        )
        self._cache[cache_key] = result
        return result

    def _estimate(self, image: Image.Image) -> Image.Image:
        if not self.model_id:
            raise RuntimeUnavailableError("Depth preprocessor model is not configured")
        try:
            import torch
            import torch.nn.functional as functional
            from transformers import AutoImageProcessor, AutoModelForDepthEstimation

            if self._processor is None:
                self._processor = AutoImageProcessor.from_pretrained(
                    self.model_id, local_files_only=self.local_files_only
                )
                self._model = AutoModelForDepthEstimation.from_pretrained(
                    self.model_id, local_files_only=self.local_files_only
                ).to(self.device)
                self._model.eval()
            inputs = {
                key: value.to(self.device)
                for key, value in self._processor(images=image, return_tensors="pt").items()
            }
            with torch.inference_mode():
                prediction = self._model(**inputs).predicted_depth
                prediction = functional.interpolate(
                    prediction.unsqueeze(1),
                    size=(image.height, image.width),
                    mode="bicubic",
                    align_corners=False,
                ).squeeze()
            low, high = prediction.min(), prediction.max()
            normalized = (prediction - low) / (high - low).clamp_min(1e-6)
            pixels = (normalized.cpu().numpy() * 255).astype("uint8")
            return Image.fromarray(pixels, mode="L").convert("RGB")
        except Exception as exc:
            raise RuntimeUnavailableError(f"Cannot create DPT depth control map: {exc}") from exc

    def unload(self) -> None:
        self._processor = None
        self._model = None
        self._cache.clear()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


def composition_canvas(
    shot: dict[str, Any],
    reference_inputs: list[dict[str, Any]],
    size: tuple[int, int],
) -> Image.Image:
    """Render a text-free spatial guide from normalized shot coordinates."""
    width, height = size
    canvas = Image.new("RGB", size, (226, 216, 201))
    draw = ImageDraw.Draw(canvas)
    horizon = round(height * 0.68)
    for y in range(height):
        if y < horizon:
            ratio = y / max(1, horizon)
            color = (238 - round(26 * ratio), 229 - round(22 * ratio), 214 - round(18 * ratio))
        else:
            ratio = (y - horizon) / max(1, height - horizon)
            color = (151 + round(34 * ratio), 119 + round(29 * ratio), 91 + round(24 * ratio))
        draw.line((0, y, width, y), fill=color)
    draw.rectangle((0, horizon - 3, width, horizon + 3), fill=(111, 82, 60))
    # A grounded bedroom guide gives img2img scene context without embedding a
    # finished background that the model must preserve literally.
    draw.rounded_rectangle(
        (round(width * 0.07), round(height * 0.12), round(width * 0.32), round(height * 0.55)),
        radius=max(8, width // 80), fill=(168, 197, 205), outline=(91, 111, 119), width=4,
    )
    draw.line(
        (round(width * 0.195), round(height * 0.12), round(width * 0.195), round(height * 0.55)),
        fill=(91, 111, 119), width=3,
    )
    draw.rectangle(
        (round(width * 0.73), round(height * 0.51), round(width * 0.97), round(height * 0.76)),
        fill=(196, 178, 151), outline=(105, 79, 58), width=4,
    )

    references_by_character: dict[str, bytes] = {}
    face_references_by_character: dict[str, bytes] = {}
    priority = {"full_body_front": 0, "three_quarter": 1, "face_closeup": 2}
    for item in sorted(
        reference_inputs, key=lambda value: priority.get(str(value.get("view_id", "")), 3)
    ):
        references_by_character.setdefault(str(item.get("character_id", "")), item["data"])
        if str(item.get("view_id", "")) == "face_closeup":
            face_references_by_character[str(item.get("character_id", ""))] = item["data"]
    for subject in shot.get("subjects", []):
        position = subject.get("position", {})
        center_x = round(float(position.get("x", 0.5)) * width)
        foot_y = round(float(position.get("y", 0.6)) * height)
        scale = str(subject.get("scale", "medium"))
        subject_height = round(height * (0.5 if "full" in scale else 0.4))
        subject_width = round(subject_height * 0.55)
        box = (
            center_x - subject_width // 2,
            foot_y - subject_height,
            center_x + subject_width // 2,
            foot_y,
        )
        character_id = str(subject.get("character_id", ""))
        source = references_by_character.get(character_id)
        if shot.get("pose_aware_scene_conditioning"):
            _draw_pose_subject(
                canvas,
                draw,
                subject=subject,
                center_x=center_x,
                foot_y=foot_y,
                subject_width=subject_width,
                subject_height=subject_height,
                face_source=face_references_by_character.get(character_id) or source,
            )
        elif source:
            reference = Image.open(io.BytesIO(source)).convert("RGB")
            cutout = _reference_cutout(reference, (subject_width, subject_height))
            shadow = Image.new("RGBA", cutout.size, (0, 0, 0, 0))
            shadow.putalpha(cutout.getchannel("A").filter(ImageFilter.GaussianBlur(8)))
            shadow_color = Image.new("RGBA", cutout.size, (45, 35, 30, 72))
            shadow_color.putalpha(shadow.getchannel("A").point(lambda value: value * 72 // 255))
            canvas.paste(shadow_color, (box[0] + 7, box[1] + 8), shadow_color)
            canvas.paste(cutout, box[:2], cutout)
        else:
            draw.ellipse(box, fill=(75, 85, 95), outline=(35, 45, 55), width=3)

    for prop in [] if shot.get("latent_props_disabled") else shot.get("prop_layout", []):
        position = prop.get("position", {})
        center_x = round(float(position.get("x", 0.5)) * width)
        center_y = round(float(position.get("y", 0.72)) * height)
        relative_width = float(prop.get("relative_width", 0.09))
        radius = max(5, round(width * relative_width / 2))
        name = str(prop.get("name", "")).casefold()
        if "paper boat" in name:
            draw.polygon([
                (center_x - radius, center_y), (center_x, center_y + radius // 2),
                (center_x + radius, center_y), (center_x + radius // 2, center_y + radius),
                (center_x - radius // 2, center_y + radius),
            ], fill=(235, 231, 215), outline=(77, 70, 61))
        elif "pillow" in name:
            fill = (79, 126, 171) if "blue" in name else (230, 190, 75)
            draw.rounded_rectangle(
                (center_x - radius, center_y - radius // 2, center_x + radius, center_y + radius // 2),
                radius=radius // 3, fill=fill, outline=(72, 65, 55), width=2,
            )
        elif "book" in name:
            draw.rectangle(
                (center_x - radius, center_y - radius // 2, center_x + radius, center_y + radius // 2),
                fill=(123, 65, 48), outline=(63, 42, 35), width=2,
            )
            draw.line((center_x, center_y - radius // 2, center_x, center_y + radius // 2), fill=(236, 220, 190), width=2)
        else:
            draw.ellipse(
                (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                fill=(105, 115, 125), outline=(45, 55, 65), width=2,
            )
    return canvas


def _draw_pose_subject(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    subject: dict[str, Any],
    center_x: int,
    foot_y: int,
    subject_width: int,
    subject_height: int,
    face_source: bytes | None,
) -> None:
    """Draw an articulated latent guide instead of pasting a full-body identity card."""
    pose = str(subject.get("pose", "")).casefold()
    seated = "seat" in pose or "sit" in pose
    head_y = foot_y - round(subject_height * (0.68 if seated else 0.88))
    shoulder_y = head_y + round(subject_height * 0.16)
    hip_y = foot_y - round(subject_height * (0.24 if seated else 0.43))
    joint = max(5, round(subject_width * 0.10))
    body = (76, 116, 151, 230)
    skin = (194, 143, 111, 235)

    # Broad connected strokes communicate bend and contact to img2img while
    # deliberately avoiding a literal full-body reference silhouette.
    draw.line((center_x, shoulder_y, center_x, hip_y), fill=body, width=joint * 3)
    if seated:
        knee_y = foot_y - round(subject_height * 0.12)
        draw.line(
            (center_x, hip_y, center_x - subject_width // 3, knee_y,
             center_x - subject_width // 3, foot_y),
            fill=body, width=joint * 2,
        )
        draw.line(
            (center_x, hip_y, center_x + subject_width // 3, knee_y,
             center_x + subject_width // 3, foot_y),
            fill=body, width=joint * 2,
        )
    else:
        draw.line((center_x, hip_y, center_x - subject_width // 4, foot_y), fill=body, width=joint * 2)
        draw.line((center_x, hip_y, center_x + subject_width // 4, foot_y), fill=body, width=joint * 2)

    interaction = subject.get("interaction_target")
    hand_y = hip_y + round(subject_height * 0.08)
    if isinstance(interaction, dict):
        hand_x = round(float(interaction.get("x", 0.5)) * canvas.width)
        hand_y = round(float(interaction.get("y", 0.6)) * canvas.height)
        draw.line((center_x, shoulder_y, hand_x, hand_y), fill=skin, width=joint)
        draw.line((center_x, shoulder_y + joint, hand_x, hand_y + joint), fill=skin, width=joint)
    else:
        draw.line((center_x, shoulder_y, center_x - subject_width // 3, hand_y), fill=skin, width=joint)
        draw.line((center_x, shoulder_y, center_x + subject_width // 3, hand_y), fill=skin, width=joint)

    face_width = max(16, round(subject_width * 0.50))
    face_height = max(20, round(subject_height * 0.21))
    face_box = (
        center_x - face_width // 2, head_y - face_height // 2,
        center_x + face_width // 2, head_y + face_height // 2,
    )
    if face_source:
        face = _identity_face(Image.open(io.BytesIO(face_source)).convert("RGB"), (face_width, face_height))
        canvas.paste(face, face_box[:2], face)
    else:
        draw.ellipse(face_box, fill=skin, outline=(86, 65, 55), width=2)


def _identity_face(reference: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Keep only a soft facial identity anchor; body pose remains fully generative."""
    reference = ImageOps.exif_transpose(reference).convert("RGB")
    side = min(reference.width, reference.height)
    left = (reference.width - side) // 2
    top = max(0, round((reference.height - side) * 0.28))
    crop = reference.crop((left, top, left + side, min(reference.height, top + side)))
    crop = ImageOps.fit(crop, size, Image.Resampling.LANCZOS)
    alpha = Image.new("L", size, 0)
    ImageDraw.Draw(alpha).ellipse((1, 1, size[0] - 2, size[1] - 2), fill=255)
    alpha = alpha.filter(ImageFilter.GaussianBlur(max(1, min(size) // 18)))
    rgba = crop.convert("RGBA")
    rgba.putalpha(alpha)
    return rgba


def _reference_cutout(reference: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Remove a near-uniform studio background and feather the identity cutout."""
    reference = ImageOps.exif_transpose(reference).convert("RGB")
    corners = [
        reference.getpixel((0, 0)), reference.getpixel((reference.width - 1, 0)),
        reference.getpixel((0, reference.height - 1)),
        reference.getpixel((reference.width - 1, reference.height - 1)),
    ]
    background = tuple(sum(pixel[channel] for pixel in corners) // 4 for channel in range(3))
    difference = ImageChops.difference(reference, Image.new("RGB", reference.size, background))
    red, green, blue = difference.split()
    distance = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    alpha = distance.point(lambda value: 0 if value < 16 else min(255, (value - 16) * 9))
    alpha = alpha.filter(ImageFilter.GaussianBlur(max(1, min(reference.size) // 300)))
    bounds = alpha.getbbox()
    if bounds:
        reference = reference.crop(bounds)
        alpha = alpha.crop(bounds)
    rgba = reference.convert("RGBA")
    rgba.putalpha(alpha)
    return ImageOps.contain(rgba, size, Image.Resampling.LANCZOS)
