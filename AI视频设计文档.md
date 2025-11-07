# 系统设计
## 实体
### 创作
一旦进入视频制作流程即生成一个创作实体

```plain
[
  {
    "creationId": "creation-1",
    "title": "不死之帝王视频创作",
    "status": "completed",
    "createdAt": "2024-01-10T10:00:00Z",
    "updatedAt": "2024-01-15T12:00:00Z",
    "associatedNovelChapters": [
      {
        "chapterId": "chapter-1",
        "novelId": "novel-1"
      }
    ],
    "characterLibrary": [
      "character-1",
      "character-2"
    ],
    "sceneList": [
      "scene-1",
      "scene-2",
      "scene-3"
    ],
    "videoUrl": "https://zhuluoji.cn-sh2.ufileos.com/images-frontend/test/video.mp4",
    "audioUrl": "https://zhuluoji.cn-sh2.ufileos.com/images-frontend/test/audio.mp3"
  }
 ]
```

### 小说
```plain
[
  {
    "novelId": "novel-1",
    "title": "不死之帝王",
    "author": "作者A",
    "uploadTime": "2024-01-01T00:00:00Z",
    "chapterList": [
      {
        "chapterId": "chapter-1",
        "title": "第一章 登基",
        "order": 1
      },
      {
        "chapterId": "chapter-2",
        "title": "第二章 朝政",
        "order": 2
      },
      {
        "chapterId": "chapter-3",
        "title": "第三章 后宫",
        "order": 3
      },
      {
        "chapterId": "chapter-4",
        "title": "第四章 征战",
        "order": 4
      },
      {
        "chapterId": "chapter-5",
        "title": "第五章 封禅",
        "order": 5
      },
      {
        "chapterId": "chapter-6",
        "title": "第六章 驾崩",
        "order": 6
      },
      {
        "chapterId": "chapter-7",
        "title": "第七章 葬礼",
        "order": 7
      },
      {
        "chapterId": "chapter-8",
        "title": "第八章 遗诏",
        "order": 8
      },
      {
        "chapterId": "chapter-9",
        "title": "第九章 继位",
        "order": 9
      }
    ],
    "relatedCreations": [
      "creation-1"
    ],
    "characterLibrary": [
      "character-1",
      "character-2"
    ]
  }
  ]
```

### 小说章节
```plain
[
  {
    "chapterId": "chapter-1",
    "title": "第一章 登基",
    "associatedNovelId": "novel-1",
    "content": "在众臣的见证下，这位年轻的帝王终于登上了至高无上的宝座。他端坐在龙椅上，目光如炬，扫视着跪拜的群臣。万岁！万岁！万万岁！声音响彻整个宫殿。\n\n朝堂之上，帝王认真听取着每一位大臣的奏报。启禀陛下，边关传来急报。一位大臣手持奏折，上前奏报。\n\n忙碌了一天的帝王，与皇后在御花园中漫步，享受着难得的宁静时光。傍晚时分的御花园，盛开的鲜花和翠绿的树木，夕阳西下，光线柔和。",
    "associatedCreation": "creation-1"
  },
  {
    "chapterId": "chapter-2",
    "title": "第二章 朝政",
    "associatedNovelId": "novel-1",
    "content": "朝堂之上，文武百官分列两侧，气氛严肃。帝王端坐在龙椅上，认真听取着每一位大臣的奏报。\n\n一位大臣上前奏报：启禀陛下，边关传来急报，需要立即处理。\n\n帝王沉思片刻，下令立即调兵遣将，前往边关支援。",
    "associatedCreation": null
  },
  {
    "chapterId": "chapter-3",
    "title": "第三章 后宫",
    "associatedNovelId": "novel-1",
    "content": "忙碌了一天的帝王，与皇后在御花园中漫步。两人手牵手，欣赏着园中的美景。\n\n皇后轻声说道：陛下，您已经很久没有这样放松过了。\n\n帝王笑了笑：是啊，难得有这样的宁静时光。",
    "associatedCreation": null
  }
 ]
```

### 角色
只有新出现的才能修改设定

```plain
[
  {
    "characterId": "character-1",
    "name": "帝王",
    "status": "new",
      "basicInfo": "35岁男性皇帝",
    "featureDescription": {
      "appearance": "威严庄重，眉宇间透露着王者之气",
      "body": "高大魁梧，身材挺拔",
      "hair": "黑色长发，束冠",
      "clothing": "黄色龙袍，金线绣龙",
      "tags": ["威严", "庄重", "王者"]
    },
    "imagePrompt": "一位威严的中年皇帝，身穿黄色龙袍，头戴金冠，面容庄重，背景是华丽的宫殿，光线从上方洒下，营造出庄严的氛围",
    "visualStyle": "写实风格，中国古代宫廷风格",
    "characterImage": "/amu.png"
  },
  {
    "characterId": "character-2",
    "name": "皇后",
    "status": "new",
    "basicInfo": "30岁女性皇后",
    "featureDescription": {
      "appearance": "美丽端庄，气质高雅",
      "body": "身材修长，体态优雅",
      "hair": "黑色盘发，佩戴凤冠",
      "clothing": "红色凤袍，金色凤凰图案",
      "tags": ["美丽", "端庄", "高雅"]
    },
    "imagePrompt": "一位美丽的皇后，身穿红色凤袍，头戴凤冠，面容端庄美丽，气质高雅，背景是华丽的宫殿，柔和的灯光",
    "visualStyle": "写实风格，中国古代宫廷风格",
    "characterImage": "/anduming.png"
  }
 ]
```

### 场景
```plain
[
  {
    "sceneId": "scene-1",
    "title": "帝王登基",
    "duration": "00:00:30",
    "sceneSetting": {
      "time": "正午",
      "location": "皇宫大殿",
      "space": "室内",
      "atmosphere": "庄严隆重"
    },
    "shotList": [
      "shot-1",
      "shot-2",
      "shot-3"
    ]
  }
]
```

### 分镜
```plain
[
  {
    "shotId": "shot-1",
    "title": "帝王登基仪式开始",
    "associatedCharacters": [
      "character-1",
      "character-2"
    ],
    "sceneDescription": "宏大的宫殿内，文武百官跪拜，帝王缓缓走向龙椅",
    "narration": "在众臣的见证下，这位年轻的帝王终于登上了至高无上的宝座",
    "imagePrompt": "宏大的宫殿内，文武百官跪拜，年轻的帝王身穿黄色龙袍，缓缓走向龙椅，光线从上方洒下，营造出庄严的氛围",
    "shotImage": "/amu.png"
  },
  {
    "shotId": "shot-2",
    "title": "帝王坐在龙椅上",
    "associatedCharacters": [
      "character-1"
    ],
    "sceneDescription": "帝王端坐在龙椅上，目光威严地扫视群臣",
    "narration": "他端坐在龙椅上，目光如炬，扫视着跪拜的群臣",
    "imagePrompt": "帝王端坐在金碧辉煌的龙椅上，身穿黄色龙袍，头戴金冠，目光威严地扫视群臣，背景是华丽的宫殿",
    "shotImage": "/anduming.png"
  }
 ]
```

## 实体属性及关系
![创作](https://cdn.nlark.com/yuque/0/2025/png/32447172/1762328702802-9e81eb72-36c5-4373-89c3-d79674e899fa.png)



![场景](https://cdn.nlark.com/yuque/0/2025/png/32447172/1762328712196-2912547f-91d5-455d-ad2d-ccb0110cf4ad.png)![角色](https://cdn.nlark.com/yuque/0/2025/png/32447172/1762328726715-f302a6bd-dbb9-4268-9143-0cccb31f76c3.png)![分镜](https://cdn.nlark.com/yuque/0/2025/png/32447172/1762328734626-ebd3e179-195c-4f7d-8618-b4616def0f55.png)![小说](https://cdn.nlark.com/yuque/0/2025/png/32447172/1762328767807-47b1e483-1b9e-4355-bfc5-eba09a2367b8.png)

![小说章节](https://cdn.nlark.com/yuque/0/2025/png/32447172/1762328775500-989f32d9-6dd3-4c42-8adc-a86f590864cf.png)

# 页面设计到的接口
## 首页
+ 涉及接口
    - 查询创作列表
    - 查询已上传小说列表

## 创作页
### 步骤1——选择剧本
+ 涉及接口
    - 上传小说
    - 查询小说及章节列表
    - 提交章节信息
        * 生成一个创作实体（返回创作id），后续步骤均在该创作下进行
        * 解析角色信息
        * 解析场景信息

### 步骤2——角色设置
+ 涉及接口
    - 查询创作信息（根据创作id， 获取创作中的角色信息）
    - 查询视觉风格列表
    - 根据角色风格生成角色图片
    - 修改角色设定
    - 重新生成单个角色图片

### 步骤3——脚本设置
+ 涉及接
    - 查询创作信息（根据创作id， 获取创作中的场景信息）
    - 修改分镜信息
    - 生成分镜图

### 步骤4——分镜图预览与修改
+ 涉及接口
    - 查询场景分镜列表
    - 修改场景提示词重新生成场景图
    - 修改旁白

### 步骤5——选择配音风格合成视频
+ 设计接口
    - 查询声音风格列表
    - 生成配音音频
    - 查询配音音频
    - 合成视频

## 创作列表
+ 涉及接口
    - 查询创作列表

## 小说管理模块
### 小说列表页
+ 涉及接口
    - 查询小说列表

### 小说详情页
+ 涉及接口
    - 根据小说id查询章节列表
    - 根据小说id查询关联角色列表
    - 根据小说id查询关联创作列表



# 
