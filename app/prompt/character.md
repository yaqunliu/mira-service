Your task is to generate a prompt for a character reference sheet (four views: facial close-up,
front, side, back), based on the character feature profile and the specified visual style.

Here is the character feature profile:
<character_features>
{{CHARACTER_FEATURES}}
</character_features>

Here is the specified visual style:
<visual_style>
{{VISUAL_STYLE}}
</visual_style>

Follow these requirements:

1. **Core requirement**: the prompt must include "horizontal landscape composition", "four-view
   layout (large facial close-up, full body front, full body side, full body back)",
   "{{VISUAL_STYLE}}", and "pure white background".
2. **Layout**: landscape orientation, laying out four distinct parts side by side:
    - A clear, large facial close-up of the character
    - Full body front view, standing
    - Full body side view, standing
    - Full body back view, standing
3. **Background and quality**:
    - The background must be pure white — no decoration, scenery, or clutter of any kind
    - No text, letters, numbers, watermarks or signatures anywhere in the image
4. **Props**: the character may hold items, weapons or props tied to their identity — if the feature
   profile describes any, include them.
5. **Consistency**: integrate everything in the feature profile — basic info, facial features, build,
   hair, clothing, and feature tags.
6. **Suggested structure**: [horizontal landscape composition], [four-view layout: large facial
   close-up, full body front, full body side, full body back], [{{VISUAL_STYLE}}], [pure white
   background], [no text or watermark], [detailed appearance and identity], [hair style and color],
   [full-body clothing and accessories], [weapons or props held].
7. **Language**: keep it concise and idiomatic for mainstream AI image tools, so the character's core
   features come through precisely.

**Output language**: write the prompt entirely in English. The character feature profile may contain
text in another language — translate it; never mix languages in the output.

Put the generated English prompt inside <提示词> tags.
