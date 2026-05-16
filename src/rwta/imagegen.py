"""OpenAI image generation for scene illustrations.

After each narrator turn we ask gpt-image-2 (low quality, 1536x1024 landscape)
to produce a single illustrative still of the current scene. Returned as a
base64 PNG so it can be shipped over the JSON-RPC channel without needing a
shared filesystem location.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

# Default to a small/cheap model. Override via env var if you want a different
# image model/size/quality. Style is now a per-render choice; default is photo.
DEFAULT_IMAGE_MODEL = os.getenv("RWTA_IMAGE_MODEL", "gpt-image-2")
DEFAULT_IMAGE_SIZE = os.getenv("RWTA_IMAGE_SIZE", "1536x1024")  # landscape
DEFAULT_IMAGE_QUALITY = os.getenv("RWTA_IMAGE_QUALITY", "low")
DEFAULT_IMAGE_STYLE_ID = os.getenv("RWTA_IMAGE_STYLE_ID", "photo")


@dataclass(frozen=True)
class ImageStyle:
    """A selectable visual style for generated scene images."""

    id: str
    name: str
    prompt: str


IMAGE_STYLES: dict[str, ImageStyle] = {
    "photo": ImageStyle(
        id="photo",
        name="Photorealistic",
        prompt=(
            "Photorealistic documentary still, natural lens perspective, realistic people, "
            "real-world materials and lighting, subtle color grading, wide establishing shot. "
            "No text overlays, no captions, no UI elements, no maps."
        ),
    ),
    "monkey_island": ImageStyle(
        id="monkey_island",
        name="Classic Adventure",
        prompt=(
            "Classic 1990s point-and-click adventure game background inspired by Monkey Island: "
            "hand-painted, whimsical, slightly exaggerated shapes, rich color, warm humor, "
            "crisp readable silhouettes, painterly 2D scene art. No text overlays, captions, UI, or maps."
        ),
    ),
    "cinematic_painterly": ImageStyle(
        id="cinematic_painterly",
        name="Cinematic Painterly",
        prompt=(
            "Cinematic widescreen still, painterly digital illustration, naturalistic lighting, "
            "muted color palette, evocative mood, wide establishing shot. No text overlays, captions, UI, or maps."
        ),
    ),
    "watercolor": ImageStyle(
        id="watercolor",
        name="Travel Watercolor",
        prompt=(
            "Loose travel-sketch watercolor and ink illustration, textured paper, luminous washes, "
            "delicate linework, plein-air atmosphere, charming but grounded. No text overlays, captions, UI, or maps."
        ),
    ),
    "noir_comic": ImageStyle(
        id="noir_comic",
        name="Noir Comic",
        prompt=(
            "Moody noir graphic novel panel, dramatic chiaroscuro lighting, expressive ink shadows, "
            "limited palette with selective color accents, cinematic composition. No speech bubbles, captions, UI, or maps."
        ),
    ),
    "pixel_art": ImageStyle(
        id="pixel_art",
        name="Pixel Art",
        prompt=(
            "High-end pixel art adventure game scene, 32-bit era detail, atmospheric dithering, "
            "readable silhouettes, richly detailed environment tiles, nostalgic but polished. No text overlays, UI, or maps."
        ),
    ),
}


@dataclass
class SceneImage:
    """A generated scene image."""

    b64_png: str
    prompt: str
    style: ImageStyle


def list_image_styles() -> list[dict[str, str]]:
    """Return available image styles as JSON-serializable dictionaries."""
    return [{"id": s.id, "name": s.name} for s in IMAGE_STYLES.values()]


def get_image_style(style_id: str | None) -> ImageStyle:
    """Return a known image style, falling back to the configured default/photo."""
    if style_id and style_id in IMAGE_STYLES:
        return IMAGE_STYLES[style_id]
    if DEFAULT_IMAGE_STYLE_ID in IMAGE_STYLES:
        return IMAGE_STYLES[DEFAULT_IMAGE_STYLE_ID]
    return IMAGE_STYLES["photo"]


def image_style_to_dict(style: ImageStyle) -> dict[str, str]:
    return asdict(style)


def _strip_suggestions(narrative: str) -> str:
    """Drop the trailing ``---\n1. ... 2. ... 3. ...`` block if present."""
    # Match a horizontal rule followed by numbered list at the very end.
    pattern = re.compile(r"\n+---\s*\n(?:\s*\d+\.\s+.+\n?)+\s*$", re.MULTILINE)
    return pattern.sub("", narrative).strip()


def build_image_prompt(
    narrative: str,
    location_str: str,
    game_time_str: str,
    weather_str: str | None = None,
    visual_continuity: str | None = None,
    style_id: str | None = None,
) -> str:
    """Build an image prompt from the most recent narrator response."""
    cleaned = _strip_suggestions(narrative)
    # Trim very long narratives — gpt-image models support long prompts, but a
    # focused prompt usually gives better composition.
    if len(cleaned) > 1800:
        cleaned = cleaned[:1800].rsplit(" ", 1)[0] + "…"

    style = get_image_style(style_id)
    parts = [
        f"STYLE: {style.name}",
        style.prompt,
        "",
        f"Setting: {location_str}.",
        f"Time: {game_time_str}.",
    ]
    if weather_str:
        parts.append(f"Weather: {weather_str}.")
    if visual_continuity:
        parts.extend(
            [
                "",
                "VISUAL CONTINUITY — highest priority:",
                "Keep recurring people, places, items, clothing, vehicles, pets, signage, and spatial layout consistent with these established facts. Only change them when the scene text explicitly says they changed. Do not redesign established elements; translate them faithfully into the selected style.",
                visual_continuity.strip(),
            ]
        )
    parts.extend(["", "Current scene to illustrate:", cleaned])
    return "\n".join(parts)


def generate_scene_image(
    narrative: str,
    location_str: str,
    game_time_str: str,
    weather_str: str | None = None,
    visual_continuity: str | None = None,
    style_id: str | None = None,
    api_key: str | None = None,
) -> SceneImage | None:
    """
    Generate a scene image for the given narrator response.

    Returns ``None`` (and logs a warning) on any failure — image gen is a
    nice-to-have, not load-bearing.
    """
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        logger.warning("OPENAI_API_KEY not set; skipping image generation")
        return None

    try:
        from openai import OpenAI, OpenAIError
    except ImportError:
        logger.warning("openai package not installed; skipping image generation")
        return None

    style = get_image_style(style_id)
    prompt = build_image_prompt(
        narrative,
        location_str,
        game_time_str,
        weather_str,
        visual_continuity,
        style.id,
    )
    logger.debug(
        "Generating image (%s, %s, style=%s)", DEFAULT_IMAGE_MODEL, DEFAULT_IMAGE_SIZE, style.id
    )

    try:
        client = OpenAI(api_key=key)
        response = client.images.generate(
            model=DEFAULT_IMAGE_MODEL,
            prompt=prompt,
            n=1,
            size=DEFAULT_IMAGE_SIZE,  # type: ignore[arg-type]
            quality=DEFAULT_IMAGE_QUALITY,  # type: ignore[arg-type]
        )
    except (OpenAIError, OSError, ValueError, TypeError) as e:
        logger.warning("Image generation failed (%s): %s", type(e).__name__, e)
        return None

    if not response.data:
        logger.warning("Image generation returned no data")
        return None

    b64 = response.data[0].b64_json
    if not b64:
        logger.warning("Image generation returned no b64_json")
        return None

    return SceneImage(b64_png=b64, prompt=prompt, style=style)
