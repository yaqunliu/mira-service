# 分镜拆解（动漫风格，全名，含运镜）

## 任务
在给定场景下拆解多个分镜（shots）。每个分镜包含画面描述、出场人物、台词/旁白、运镜方式、景别。

## 输入
```
[场景文本]

[角色特征库 JSON]
```

## 输出格式（JSON）
```
{
  "shots": [
    {
      "shot_id": 1,
      "description": "画面描述，强调动画风格" ,
      "characters": ["角色名-状态", "..."],
      "dialogues": ["角色1: ...", "旁白: ..."],
      "script": "分镜剧本正文",
      "camera_movement": "(如 dolly in / pan / tilt / tracking / orbital / crane / handheld / quick cut / freeze frame / slow motion / fast motion)",
      "shot_size": "(如 extreme wide / wide / full / medium / medium close-up / close-up / extreme close-up)",
      "angle": "(eye level / high / low / dutch)",
      "reference_images": []
    }
  ]
}
```

## 规则
- 人物名称必须使用角色特征库中的完整名称（含状态）。
- 画面描述默认采用**动画风格（anime style）**，避免写实/照片描述。
- 参考图列表允许为空；如果为空，后续将使用文生图生成。
- 输出仅 JSON，无额外说明。
