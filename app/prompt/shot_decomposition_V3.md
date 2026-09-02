你的任务是根据提供的原文文案、场景信息和角色特征库，将每个场景拆解成多个分镜。

## 输入信息

### 原文文案
以下是完整的原文文案（包含所有剧情细节）：
<original_text>
{{ORIGINAL_TEXT}}
</original_text>

### 角色特征库
以下是已识别的角色列表。**引用角色时必须使用 `id` 数字，禁止复述角色名**：
<character_list>
{{CHARACTER_LIST}}
</character_list>

### 场景信息
以下是场景的环境设定（场景是空舞台，只包含环境信息）。
每个场景的字段为 `scene_number`（编号）、`title`（场景标题）、`environment`（环境设定，含
`time_setting` / `location` / `space_type` / `space_description` / `atmosphere` / `environment_description`），
**取值均为英文**：
<scenes>
{{SCENES}}
</scenes>

## 任务要求

### 总体时长规范

**关键要求**：整个剧本文案的分镜总时长应控制在 **90-150 秒**之间

- **分镜数量**：通常拆分为 **15-25 个分镜**
- **平均时长**：每个分镜平均 5-7 秒
- **单个分镜时长上限**：**严禁超过 8 秒**。如果内容较多，请拆分为多个分镜。
- **时长计算**：确保所有分镜时长之和在 90-150 秒范围内

### 分镜拆解规则

1. **分镜编号 (shot_number)**：使用"场景编号-分镜序号"格式（如："1-1", "1-2", "2-1"），场景编号取自场景表的 `scene_number`

2. **关联场景**：每个分镜必须输出 `scene_number`（整数，与场景表的 `scene_number` 一致）和 `scene_title`（原样复制场景表的 `title`，不要改写或翻译）

3. **构图要求**：
   - **每个分镜的开始必须以近景（Medium Close-up）且人物居中的构图开始。**
   - 画面应聚焦于角色的面部表情或核心动作，增强视觉冲击力。

4. **出镜角色 (on_screen_character_ids)**：列出分镜中**实际出镜**的角色
   - **必须使用角色特征库表格中的 `id` 数字，禁止输出角色名**
   - 例如角色表中有 `- id=42 | name=Tao Wei | type=on_screen | age_group=youth | state=drenched`，
     则输出 `"on_screen_character_ids": [42]`
   - **同一人物的不同 state 是不同的 id**，必须按当前分镜的实际外观状态选择对应的 id
     （例如角色在雨中湿透，就要选 `state=drenched` 那一条的 id，而不是 `state=-` 的那条）
   - **核心标准：当前分镜中出现的人物必须在分镜一开始就出现在画面中，严禁在镜头中途才进入画面。**
   - **如果需要中途出现新的人物，必须拆分为一个新的分镜。**
   - 只包含实际出现在画面中的角色（`type=on_screen`）。

5. **声音角色 (voice_character_ids)**：列出分镜中**未出镜但有声音**的角色
   - 通过电话、画外音、回忆声音等方式出现的角色。
   - 同样**必须使用 `id` 数字**，取角色表中 `type=voice` 的条目。

6. **出镜元素 (appearance_elements)**：列出分镜中**实际出现**的关键物品、工具或道具
   - 如：手机、包包、武器、书信、特定家具、车辆等。
   - 确保分镜中描述的重要道具在这里被明确列出，以便后续生成提示词时不会遗漏。
   - **元素名称用英文**（如 `"a stack of new textbooks"`、`"failure report"`）。

7. **台词 (narration)**：列出分镜中角色的第一人称声音（对话、心理独白、电话声音）
   - **必须以对象数组形式输出**，每项包含 `character_id` 与 `content`，
     例如：`[{"character_id": 42, "content": "Professor, I found the map!"}]`
   - `character_id` 同样取角色表中的 `id`；**禁止输出角色名**
   - **台词内容 `content` 必须是英文。**
   - **禁止添加第三人称旁白描述**。
   - **台词时长估算**：包含标点符号，平均每秒 2.5 个英文单词。

8. **分镜时长 (duration)**：控制在 3-8 秒之间
   - **严禁超过 8 秒**。
   - 如果台词内容在 8 秒内无法说完，**必须**将该分镜拆分为两个或多个分镜，并合理分配台词。
   - **计算公式**：台词单词数 ÷ 2.5 + 1.5秒（留出画面停留时间），且结果不能超过 8。

9. **简要剧情 (description)**：精简描述分镜的剧情内容（20-35 个英文单词）
   - 概括这个分镜发生了什么，重点描述角色的动作和情节发展。
   - **必须是英文。**
   - 🔥 **必须写角色的名字，严禁写 `id` 数字** 🔥
     - `description` 是给人阅读的自然语言叙述，会直接显示在用户界面上。
     - 「用 id 引用角色」这条规则**只适用于** `on_screen_character_ids`、
       `voice_character_ids` 和 `narration[].character_id` 这三个字段。
     - ✅ 正确：`"Medium close-up, centered: Tao Wei stands at the classroom door..."`
     - ❌ 错误：`"Medium close-up, centered: 51 stands at the classroom door..."`
     - 角色名取角色表 `name` 列的值，**不要**附带 `age_group` / `state` 后缀。

## 重要规则

1. **单个分镜时长（硬性要求）**：
   - **严禁超过 8 秒**。
   - 每个分镜的节奏要快，保持动态感。

2. **人物出场时机（硬性要求）**：
   - **所有关联的出镜角色必须在分镜开始的第 0 秒就位于画面中。**
   - 不允许出现“人物从画外走入”或“镜头旋转到一半才看到某人”的情况。

3. **构图起始（硬性要求）**：
   - **每个分镜必须以人物近景且居中作为起始画面。**

4. **总时长控制**：
   - 所有分镜时长之和必须在 90-150 秒范围内。

5. **台词格式**：
   - 必须是对象数组格式，每项为 `{"character_id": <id>, "content": "..."}`，只包含第一人称声音。

6. **输出语言（硬性要求）**：
   - `description`、`narration[].content`、`appearance_elements`、`camera_movement`、
     `sound_effect`、`script_content` 全部**必须是英文**。
   - `scene_title` 原样复制场景表的 `title`（已是英文），不要改写或翻译。
   - 即使原文文案是中文，输出也必须是英文。

## 输出格式

请将结果放在 `<分镜拆解>` 标签内，输出 JSON 格式。

以下示例假设角色表为：
```
- id=42 | name=Lin Xiaoyu | type=on_screen | age_group=youth | state=-
- id=43 | name=Professor Chen | type=voice | age_group=- | state=- | voice_channel=phone
```

```json
{
  "shots": [
    {
      "shot_number": "1-1",
      "scene_number": 1,
      "scene_title": "Rare Books Library",
      "on_screen_character_ids": [42],
      "appearance_elements": ["yellowed parchment map", "ancient tomes"],
      "voice_character_ids": [],
      "narration": [],
      "duration": 6,
      "description": "Medium close-up, centered: Lin Xiaoyu pores over an ancient tome, then spots a yellowed parchment map between the pages and her eyes widen in surprise."
    },
    {
      "shot_number": "1-2",
      "scene_number": 1,
      "scene_title": "Rare Books Library",
      "on_screen_character_ids": [42],
      "appearance_elements": ["yellowed parchment map", "ancient tomes"],
      "voice_character_ids": [43],
      "narration": [{"character_id": 42, "content": "Professor, I found the map!"}],
      "duration": 5,
      "description": "Medium close-up, centered: Lin Xiaoyu lifts her phone, reporting the discovery to the professor with mounting excitement."
    }
  ]
}
```

请严格按照以上格式输出，确保 JSON 格式正确，所有字段完整。

## 正确与错误示例说明

### ✅ 正确示例

**示例1：严格控制时长与起始构图**
```json
{
  "shot_number": "2-1",
  "on_screen_character_ids": [51],
  "appearance_elements": ["failure report"],
  "duration": 6,
  "description": "Medium close-up, centered: Tao Wei's face is pale, despair in his eyes as he stares down at the failure report in front of him.",
  "narration": [{"character_id": 51, "content": "Not again... am I really not good enough?"}]
}
```
*解析：时长 6s（未超8s），description 指明了"近景居中"并用角色名叙述，台词为第一人称独白，
`on_screen_character_ids` 与 `narration[].character_id` 一律用 id 引用。*

**示例2：新人物出现强制拆分分镜**
```json
[
  {
    "shot_number": "3-1",
    "on_screen_character_ids": [42],
    "appearance_elements": [],
    "description": "Medium close-up, centered: Lin Xiaoyu runs through the rain, panic on her face.",
    "duration": 5
  },
  {
    "shot_number": "3-2",
    "on_screen_character_ids": [42, 60],
    "appearance_elements": ["the stranger's umbrella"],
    "description": "Medium close-up, centered: a stranger blocks Lin Xiaoyu's path, the two of them locked in a standoff.",
    "duration": 4
  }
]
```
*解析：神秘人出现时立即拆分为新分镜，确保每个分镜开始时角色就在画面中。*

**示例3：同一人物的不同外观状态要选对 id**

角色表：
```
- id=51 | name=Tao Wei | type=on_screen | age_group=youth | state=-
- id=52 | name=Tao Wei | type=on_screen | age_group=youth | state=drenched
```
雨中湿透的分镜必须用 `52`，办公室日常的分镜必须用 `51`：
```json
{ "shot_number": "4-1", "on_screen_character_ids": [52], "description": "Medium close-up, centered: Tao Wei stands in the rain, soaked through." }
```
*解析：选错 id 会导致生图时套用错误的角色参考图，画面与剧情不符。
注意 `description` 里写的是名字 `Tao Wei`，不是 id `52`。*

### ❌ 错误示例

**错误1：时长超过 8 秒**
```json
❌ "duration": 12,
❌ "description": "Lin Xiaoyu searches the library for a long time, finally finds the map, sits down to study it carefully, and then takes out her phone to photograph it."
```
*修正：动作过多导致时长过长，应拆分为 2-3 个分镜。*

**错误2：人物中途入场**
```json
❌ "on_screen_character_ids": [51, 73],
❌ "description": "Medium close-up, centered: Tao Wei is working when Director Li pushes the door open and walks over to him."
```
*修正：李总是在分镜中途进入的。应改为：分镜A（只有陶未），分镜B（两人都在画面中）。*

**错误3：非近景居中起始**
```json
❌ "description": "Wide shot: the entire city is shrouded in heavy rain, the library glowing in the distance."
```
*修正：起始画面必须是人物近景且居中。环境描述应融入角色互动的背景中。*

**错误4：包含第三人称旁白**
```json
❌ "narration": [{"character_id": null, "content": "He felt a fear he had never known before."}]
```
*修正：应改为角色的第一人称心理独白或通过面部表情动作（description）来体现。*

**错误5：用角色名而不是 id 引用角色**
```json
❌ "on_screen_character_ids": ["Tao Wei", "Director Li"],
❌ "narration": [{"role": "Tao Wei", "content": "..."}]
```
*修正：必须写成 `"on_screen_character_ids": [51, 73]` 与 `"narration": [{"character_id": 51, "content": "..."}]`。
角色名会导致后端无法定位到具体的角色变体，进而套错参考图或配错音色。*

**错误6：把 id 数字写进 description（🔥 高频错误）**
```json
❌ "description": "Medium close-up, centered: 10 carries a stack of new textbooks and stands at the classroom door, slightly out of breath."
```
*修正：`description` 是给人阅读的叙述文本，会直接显示在用户界面上，必须写角色名：*
```json
✅ "description": "Medium close-up, centered: Tao Wei carries a stack of new textbooks and stands at the classroom door, slightly out of breath."
```
*「用 id 引用角色」只适用于 `on_screen_character_ids`、`voice_character_ids`、
`narration[].character_id` 三个字段，**不适用于任何叙述性文本**。*

**错误7：输出中文**
```json
❌ "description": "近景居中：陶未抱着一摞新课本站在教室门口，微微喘气。"
❌ "appearance_elements": ["新课本", "教室门"]
```
*修正：即使原文文案是中文，`description`、`narration[].content`、`appearance_elements`
等字段也必须输出英文。*
