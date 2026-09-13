# -*- coding: utf-8 -*-
# COVER_STYLE_COLLECTION — selectable art styles for article covers.
# Research sources: Ollama web search (Midjourney style references — willwulfken's
# Styles-and-Keywords-Reference repo, midlibrary.io, prompt-architects.com 2026
# style-modifier reference) + Indian GI-tagged painting traditions (memeraki,
# ragaarts). Curated 2026-09-13 per user directive "collection of different
# styles to choose from".
#
# Structure per style:
#   name      — short label (stored in article doc / shown in tooling)
#   suffix    — appended to the scene hint in the cover prompt (replaces
#               _PAINTING_STYLE_SUFFIX). All styles MUST keep the invariants:
#               scene right two-thirds, LEFT third smooth soft-white gradient
#               (app overlays the title), NO text/borders/watermarks.

COVER_STYLE_COLLECTION = [
    # ---- Indian classical painting traditions ----
    {
        "name": "Classical Devotional Painting",
        "suffix": (
            "Classical Indian devotional painting style with rich jewel tones and gold accents, "
            "in the manner of traditional temple art. The scene occupies the right two-thirds "
            "of the frame. The LEFT third must be a smooth, soft plain white/ivory gradient "
            "(empty negative space — the app overlays the title there). Absolutely NO text, "
            "no letters, no logos, no watermarks, no borders, no frames."
        ),
    },
    {
        "name": "Tanjore Gold Leaf",
        "suffix": (
            "Tanjore (Thanjavur) painting style — classical South Indian art with embossed "
            "gold leaf gilding, inlaid gems, rich saturated reds and deep greens, rounded "
            "serene figures with almond eyes. The scene occupies the right two-thirds of the "
            "frame. The LEFT third must be a smooth, soft plain cream gradient (empty negative "
            "space for the app title overlay). Absolutely NO text, no letters, no logos, "
            "no watermarks, no borders."
        ),
    },
    {
        "name": "Pattachitra",
        "suffix": (
            "Odisha Pattachitra folk painting style — intricate line work, bold red black "
            "and white natural pigments with ochre and indigo accents, decorative floral "
            "borders within the scene, devotional iconography. The scene occupies the right "
            "two-thirds of the frame. The LEFT third must be a smooth, soft plain ivory "
            "gradient (empty negative space for the app title overlay). Absolutely NO text, "
            "no letters, no watermarks, no outer border."
        ),
    },
    {
        "name": "Madhubani Folk",
        "suffix": (
            "Madhubani (Mithila) folk painting style — dense fine-line patterns, double-figure "
            "work, vibrant natural dye colors (yellow, red, green, indigo), decorative fish "
            "lotus and peacock motifs filling the composition. The scene occupies the right "
            "two-thirds of the frame. The LEFT third must be a smooth, soft plain warm-white "
            "gradient (empty negative space). Absolutely NO text, no letters, no watermarks, "
            "no borders."
        ),
    },
    {
        "name": "Mysore Soft Gouache",
        "suffix": (
            "Mysore painting style — gentle gouache devotional art, soft luminous skin tones, "
            "delicate gold foil highlights, calm symmetrical composition on a deep green or "
            "maroon ground. The scene occupies the right two-thirds of the frame. The LEFT "
            "third must be a smooth, soft plain ivory gradient (empty negative space). "
            "Absolutely NO text, no letters, no watermarks, no borders."
        ),
    },
    {
        "name": "Pahari Miniature",
        "suffix": (
            "Pahari-Rajput miniature painting style — delicate brushwork, luminous natural "
            "pigments, lyrical landscapes with stylized trees and rivers, elegant figures "
            "with fine profile lines, soft gold sky. The scene occupies the right two-thirds "
            "of the frame. The LEFT third must be a smooth, soft plain aged-paper cream "
            "gradient (empty negative space). Absolutely NO text, no calligraphy, no "
            "watermarks, no borders."
        ),
    },
    {
        "name": "Bengal Pat Watercolor",
        "suffix": (
            "Bengal patua (kalighat pat) watercolor style — flowing single-stroke outlines, "
            "simplified bold figures, muted earth palette with accent vermillion, matte "
            "handmade-paper texture. The scene occupies the right two-thirds of the frame. "
            "The LEFT third must be a smooth, soft plain paper-white gradient (empty negative "
            "space). Absolutely NO text, no letters, no watermarks, no borders."
        ),
    },
    # ---- Devotional / cinematic rendering ----
    {
        "name": "Divine Light Photography",
        "suffix": (
            "Cinematic devotional photography style — a serene real-world scene with volumetric "
            "golden-hour god rays, shallow depth of field, soft glowing highlights, gentle "
            "film grain. The subject sits in the right two-thirds of the frame. The LEFT third "
            "must be a smooth, soft out-of-focus white gradient (empty negative space for the "
            "app title overlay). Absolutely NO text, no letters, no watermarks."
        ),
    },
    {
        "name": "Temple Stone & Mist",
        "suffix": (
            "Atmospheric photographic style — ancient Indian temple architecture (gopurams, "
            "stone carvings, diya lamps) in morning mist, muted sandalwood and indigo palette, "
            "soft diffused dawn light. The architecture sits in the right two-thirds of the "
            "frame. The LEFT third must be a smooth, soft pale mist-white gradient (empty "
            "negative space). Absolutely NO text, no letters, no watermarks, no borders."
        ),
    },
    # ---- Serene / minimalist (close to the old Zen style, no baked text) ----
    {
        "name": "Zen Minimal Watercolor",
        "suffix": (
            "Minimalist Zen sumi-e watercolor style — sparse elegant brushwork, generous "
            "negative space, muted indigo sandalwood and gold wash palette, a single focal "
            "element (deity, lamp, lotus, bird or tree). The subject sits in the right "
            "two-thirds of the frame. The LEFT third must be a smooth, soft plain warm-white "
            "wash gradient (empty negative space). Absolutely NO text, no calligraphy, no "
            "seals, no watermarks."
        ),
    },
    {
        "name": "Gond Tribal Art",
        "suffix": (
            "Gond tribal art style — rhythmic dot-and-line patterning, flowing stylized "
            "flora and fauna, vivid flat colors (teal, ochre, crimson, white) on a deep "
            "earthen ground. The composition fills the right two-thirds of the frame. The "
            "LEFT third must be a smooth, soft plain cream gradient (empty negative space). "
            "Absolutely NO text, no letters, no watermarks, no borders."
        ),
    },
    {
        "name": "Kerala Mural",
        "suffix": (
            "Kerala mural painting style — classical fresco tradition with pancavarna "
            "five-color scheme (yellow, red, green, blue, white), ornate eye-elaborate "
            "figures, decorative gopuram and floral backdrop. The scene occupies the right "
            "two-thirds of the frame. The LEFT third must be a smooth, soft plain warm "
            "plaster-white gradient (empty negative space). Absolutely NO text, no letters, "
            "no watermarks, no borders."
        ),
    },
]

DEFAULT_COVER_STYLE = "Classical Devotional Painting"


def get_cover_style(name: str = None) -> dict:
    """Return a style dict from COVER_STYLE_COLLECTION (default fallback)."""
    if not name:
        name = DEFAULT_COVER_STYLE
    for s in COVER_STYLE_COLLECTION:
        if s["name"].lower() == (name or "").strip().lower():
            return s
    return next(s for s in COVER_STYLE_COLLECTION if s["name"] == DEFAULT_COVER_STYLE)