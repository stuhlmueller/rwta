import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.imagegen import build_image_prompt, get_image_style, list_image_styles  # noqa: E402


class TestImageGenerationPrompt(unittest.TestCase):
    def test_prompt_includes_visual_continuity_as_high_priority(self) -> None:
        prompt = build_image_prompt(
            narrative="You step onto the amphitheater stage.\n\n---\n1. Wave\n2. Sit\n3. Leave",
            location_str="Moraga Commons Park, Moraga, CA",
            game_time_str="Saturday morning",
            weather_str="Clear sky",
            visual_continuity=(
                "- Protagonist wears a red rain jacket and carries a brass compass.\n"
                "- The amphitheater has a white curved bandshell and green lawn bowl."
            ),
            style_id="monkey_island",
        )

        self.assertIn("STYLE: Classic Adventure", prompt)
        self.assertIn("VISUAL CONTINUITY — highest priority", prompt)
        self.assertIn("red rain jacket", prompt)
        self.assertIn("brass compass", prompt)
        self.assertIn("white curved bandshell", prompt)
        self.assertIn("Only change them when the scene text explicitly says", prompt)
        self.assertNotIn("1. Wave", prompt)
        self.assertIn("Current scene to illustrate", prompt)

    def test_prompt_omits_empty_visual_continuity_section(self) -> None:
        prompt = build_image_prompt(
            narrative="A quiet street.",
            location_str="Oakland, CA",
            game_time_str="Noon",
            visual_continuity=None,
        )

        self.assertNotIn("VISUAL CONTINUITY", prompt)
        self.assertIn("STYLE: Photorealistic", prompt)
        self.assertIn("A quiet street.", prompt)

    def test_styles_include_photo_default_and_monkey_island(self) -> None:
        styles = {style["id"]: style["name"] for style in list_image_styles()}
        self.assertEqual(get_image_style(None).id, "photo")
        self.assertEqual(styles["photo"], "Photorealistic")
        self.assertEqual(styles["monkey_island"], "Classic Adventure")


if __name__ == "__main__":
    unittest.main()
