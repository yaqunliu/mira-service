"""
StoryboardDirector Node 集成测试

测试两步 LLM 流程：
1. LLM 生成分镜脚本 → save_shots Tool
2. LLM 生成图片提示词 → save_shot_prompts Tool  
3. generate_shot_images Tool 触发任务
"""

import asyncio
import sys
sys.path.insert(0, '/app')

from app.agent.graph.nodes.teams.storyboard_director import StoryboardDirectorNode
from app.agent.state.schemas import ProductionStage


def test_json_parsing():
    """测试 JSON 解析的各种情况"""
    print("\n" + "=" * 50)
    print("测试 1: JSON 解析能力")
    print("=" * 50)
    
    node = StoryboardDirectorNode()
    
    # 测试用例
    test_cases = [
        # 正常情况
        ('正常 JSON', '''[{"scene_name": "咖啡厅", "title": "初次相遇", "description": "测试", "narration": [], "duration": 5}]'''),
        
        # 带 markdown 代码块
        ('Markdown 代码块', '''```json
[{"scene_name": "咖啡厅", "title": "初次相遇", "description": "测试", "narration": [], "duration": 5}]
```'''),
        
        # 尾部多余逗号
        ('尾部逗号', '''[{"scene_name": "咖啡厅", "title": "初次相遇", "description": "测试", "narration": [], "duration": 5,}]'''),
        
        # 未闭合括号
        ('未闭合括号', '''[{"scene_name": "咖啡厅", "title": "初次相遇", "description": "测试", "narration": [], "duration": 5}'''),
        
        # 多个对象
        ('多个对象', '''[
    {"scene_name": "场景1", "title": "分镜1", "description": "描述1", "narration": [], "duration": 5},
    {"scene_name": "场景2", "title": "分镜2", "description": "描述2", "narration": [], "duration": 6}
]'''),
        
        # 中文内容
        ('中文内容', '''[{"scene_name": "高铁站出站口", "title": "寒风中的电话", "description": "傍晚时分，林晚拖着银色行李箱走出高铁站", "narration": [{"角色": "林晚", "内容": "爸，我到站了"}], "duration": 5}]'''),
    ]
    
    passed = 0
    for name, test_json in test_cases:
        result = node._parse_json_response(test_json)
        if result and isinstance(result, list) and len(result) > 0:
            print(f"  ✅ {name}: 成功，解析出 {len(result)} 项")
            passed += 1
        else:
            print(f"  ❌ {name}: 失败")
    
    print(f"\n解析测试: {passed}/{len(test_cases)} 通过")
    return passed == len(test_cases)


def test_node_instantiation():
    """测试 Node 实例化"""
    print("\n" + "=" * 50)
    print("测试 2: Node 实例化")
    print("=" * 50)
    
    try:
        node = StoryboardDirectorNode()
        
        # 检查关键属性
        checks = [
            ("有 SCRIPT_PROMPT", hasattr(node, 'SCRIPT_PROMPT')),
            ("有 PROMPT_GENERATION_PROMPT", hasattr(node, 'PROMPT_GENERATION_PROMPT')),
            ("有 run 方法", hasattr(node, 'run')),
            ("有 _parse_json_response 方法", hasattr(node, '_parse_json_response')),
            ("有 LLM", hasattr(node, 'llm') and node.llm is not None),
        ]
        
        all_passed = True
        for check_name, passed in checks:
            status = "✅" if passed else "❌"
            print(f"  {status} {check_name}")
            if not passed:
                all_passed = False
        
        return all_passed
    except Exception as e:
        print(f"  ❌ 实例化失败: {e}")
        return False


def test_mock_run():
    """测试 run 方法（无实际 LLM 调用）"""
    print("\n" + "=" * 50)
    print("测试 3: Run 方法（无 script_text）")
    print("=" * 50)
    
    async def _test():
        node = StoryboardDirectorNode()
        
        # 测试无 script_text 情况
        state = {
            "creation_uuid": "test-uuid",
            "script_text": None,
        }
        
        result = await node.run(state)
        
        if result.get("needs_input") and result.get("production_stage") == ProductionStage.INIT:
            print("  ✅ 正确返回需要输入状态")
            return True
        else:
            print(f"  ❌ 返回异常: {result}")
            return False
    
    return asyncio.run(_test())


if __name__ == "__main__":
    print("\n🚀 开始 StoryboardDirector Node 测试...\n")
    
    results = []
    
    results.append(("JSON 解析", test_json_parsing()))
    results.append(("Node 实例化", test_node_instantiation()))
    results.append(("Run 方法", test_mock_run()))
    
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {status}: {name}")
    
    passed_count = sum(1 for _, p in results if p)
    print(f"\n总计: {passed_count}/{len(results)} 通过")
    
    if passed_count == len(results):
        print("\n✅ 所有测试通过！")
    else:
        print("\n❌ 部分测试失败")
        sys.exit(1)
