Your task is to generate an image prompt for a scene environment plate, based on the scene's
environment settings and the specified visual style.

## Key Requirements

1. **Style**: follow the specified visual style exactly — no other style
2. **Empty scene**: **no people, characters, or humanoid figures** may appear
3. **Environment only**: describe only environment, architecture, objects, landscape, weather, light
4. **16:9 landscape composition**: framing and viewpoint suited to a horizontal image

## Input

The scene's environment settings:

<scene_environment>
{{SCENE_ENVIRONMENT}}
</scene_environment>

The specified visual style:
<visual_style>
{{VISUAL_STYLE}}
</visual_style>

## What the Prompt Must Contain

1. **Style declaration**
   - Open with: {{VISUAL_STYLE}}
   - Emphasise: high quality background

2. **The subject of the scene**
   - Place name and spatial character
   - Architectural structure or natural landscape
   - Principal objects and decorative elements

3. **Time and light**
   - Time of day (dusk, deep night, early morning...)
   - Lighting (neon, moonlight, sunlight...)
   - How light and shadow shift, and the mood they create

4. **Weather and motion**
   - Weather (rain, clear, fog...)
   - Moving elements (raindrops, smoke, drifting light...)
   - Environmental detail in motion

5. **Palette and atmosphere**
   - Dominant palette (cool, warm...)
   - Emotional atmosphere (oppressive, warm, mysterious...)
   - Overall texture of the image

### Prohibited

❌ **Never include**:
- Any person, character, or human figure
- Person-related words (man, woman, person, character, protagonist...)
- Body parts (hand, face, body...)
- Human actions (standing, walking, sitting...)
- Clothing or accessories (unless present as a static prop)

✅ **Allowed**:
- Buildings, rooms, streets
- Natural landscape (mountains, water, trees, sky...)
- Objects and props (furniture, lamps, vehicles...)
- Weather and lighting effects
- Atmosphere and mood

## Output Format

**Output language**: write the prompt entirely in English. The scene environment settings may
contain text in another language — translate it. Never mix languages, and use English punctuation
throughout.

Output **only the prompt itself** — no tags, no code fences, no explanation. The entire response is
used directly as the image generation prompt.

**Structure** (a skeleton showing what to write in what order — do not copy the bracket labels
literally):

```
{{VISUAL_STYLE}}, high quality background. 16:9 landscape composition.

[Location]: [spatial character], [architecture or landscape structure].

Time: [time of day], [lighting]. Weather: [conditions], [motion effects].

Environment detail: [principal objects], [decorative elements], [background elements]. [Position and state of specific items].

Palette: [dominant colors], [light and shadow]. Atmosphere: [mood], [image texture].

Motion: [raindrops, smoke, drifting light and similar moving elements].

High quality, no people, empty scene.
```

## Example

### Input

```json
{
  "time_setting": "dusk",
  "location": "A bus stop beside a city street",
  "space_description": "A cramped half-open waiting area enclosed by a plastic canopy and low railings on both sides, the ground slick concrete, a road with sparse traffic in front",
  "background_elements": "Rain-washed advert lightbox, standing water reflecting blurred neon, soaked benches, scattered flyers and shreds of paper in the puddles",
  "atmosphere": "Oppressive, lonely, damp"
}
```

### Output

```
anime style, japanese animation, cel shading, high quality animated background. 16:9 landscape composition.

A bus stop beside a city street: a cramped half-open waiting area, rain drumming hard on the plastic canopy, low railings enclosing both sides, the ground slick wet concrete, a road with sparse traffic ahead.

Time: dusk, the sky gone grey, streetlights just coming on. Weather: heavy downpour, rain sheeting off the canopy edge, standing water throwing back neon highlights.

Environment detail: a rain-washed advert lightbox flickering unevenly, wet metal benches glazed with water, flyers scattered across the ground and soaked through, scraps of paper floating in the puddles. Headlights trail streaks of light on the road beyond.

Palette: predominantly cool, blue-violet neon mixed with dim yellow streetlight, a wet sheen throughout. Atmosphere: oppressive, lonely, damp — the desolation of a rainy night.

Motion: rain running continuously off the canopy, ripples spreading across the water's surface, neon flickering in reflection, a passing car throwing up spray in the distance.

High quality, no people, empty scene.
```

## Self-check

Before finishing, verify:
- ✅ Is the specified visual style declared?
- ✅ Is 16:9 landscape composition emphasised?
- ✅ Is the prompt entirely free of people?
- ✅ Does it cover time, place, weather and light?
- ✅ Does it describe environmental detail and atmosphere?
- ✅ Does it include motion?
- ✅ Does it end on "no people, empty scene"?
- ✅ Is every word English, with no language mixing?
- ✅ Is it the bare prompt only — no tags, no code fences, no explanation?

Now generate the scene image prompt.
