"""
StoryboardDirector 端到端集成测试

测试完整流程：
1. save_shots Tool
2. save_shot_prompts Tool  
3. generate_shot_images Tool
"""

import asyncio
import sys
sys.path.insert(0, '/app')

from app.core.logger import logger


async def test_save_shots_tool():
    """测试 save_shots Tool"""
    print("\n" + "=" * 50)
    print("测试 1: save_shots Tool")
    print("=" * 50)
    
    from app.agent.tools.db_tools import save_shots
    
    # 模拟分镜数据
    mock_shots = [
        {
            "scene_name": "测试场景",
            "title": "测试分镜",
            "description": "这是一个测试分镜描述",
            "narration": [{"角色": "旁白", "内容": "测试内容"}],
            "duration": 5,
        }
    ]
    
    try:
        # 这会因为没有真实 creation_uuid 而失败，但验证了 Tool 可调用
        result = await save_shots.ainvoke({
            "creation_uuid": "00000000-0000-0000-0000-000000000001",
            "shots": mock_shots,
        })
        
        if not result.get("success"):
            # 预期失败：创作项目不存在
            if "创作项目不存在" in str(result.get("error", "")):
                print("  ✅ Tool 可调用，正确返回 '创作项目不存在' 错误")
                return True
            else:
                print(f"  ⚠️ 意外错误: {result}")
                return False
        else:
            print(f"  ⚠️ 不应该成功: {result}")
            return False
    except Exception as e:
        print(f"  ❌ Tool 调用失败: {e}")
        return False


async def test_save_shot_prompts_tool():
    """测试 save_shot_prompts Tool"""
    print("\n" + "=" * 50)
    print("测试 2: save_shot_prompts Tool")
    print("=" * 50)
    
    from app.agent.tools.db_tools import save_shot_prompts
    
    mock_prompts = [
        {
            "shot_number": 1,
            "image_prompt": "A test scene with anime style",
            "end_frame_prompt": "Same scene, end state",
        }
    ]
    
    try:
        result = await save_shot_prompts.ainvoke({
            "creation_uuid": "00000000-0000-0000-0000-000000000001",
            "prompts": mock_prompts,
        })
        
        if not result.get("success"):
            if "创作项目不存在" in str(result.get("error", "")):
                print("  ✅ Tool 可调用，正确返回 '创作项目不存在' 错误")
                return True
            else:
                print(f"  ⚠️ 意外错误: {result}")
                return False
        else:
            print(f"  ⚠️ 不应该成功: {result}")
            return False
    except Exception as e:
        print(f"  ❌ Tool 调用失败: {e}")
        return False


async def test_generate_shot_images_tool():
    """测试 generate_shot_images Tool"""
    print("\n" + "=" * 50)
    print("测试 3: generate_shot_images Tool")
    print("=" * 50)
    
    from app.agent.tools.db_tools import generate_shot_images
    
    try:
        result = await generate_shot_images.ainvoke({
            "creation_uuid": "00000000-0000-0000-0000-000000000001",
            "force_regenerate": False,
        })
        
        if not result.get("success"):
            if "创作不存在" in str(result.get("error", "")):
                print("  ✅ Tool 可调用，正确返回 '创作不存在' 错误")
                return True
            else:
                print(f"  ⚠️ 意外错误: {result}")
                return False
        else:
            print(f"  ⚠️ 不应该成功: {result}")
            return False
    except Exception as e:
        print(f"  ❌ Tool 调用失败: {e}")
        return False


async def test_celery_task_import():
    """测试 Celery Task 导入"""
    print("\n" + "=" * 50)
    print("测试 4: agent_shot_task 导入")
    print("=" * 50)
    
    try:
        from app.tasks.agent_shot_task import agent_generate_shot_images_task
        print(f"  ✅ Task 导入成功: {agent_generate_shot_images_task.name}")
        return True
    except Exception as e:
        print(f"  ❌ 导入失败: {e}")
        return False


async def test_node_full_flow():
    """测试 Node 完整流程（无 LLM 调用）"""
    print("\n" + "=" * 50)
    print("测试 5: Node 完整流程检查")
    print("=" * 50)
    
    from app.agent.graph.nodes.teams.storyboard_director import StoryboardDirectorNode
    from app.agent.state.schemas import ProductionStage
    
    node = StoryboardDirectorNode()
    
    # 检查所有关键方法
    checks = [
        ("SCRIPT_PROMPT 包含 scene_name", "scene_name" in node.SCRIPT_PROMPT),
        ("SCRIPT_PROMPT 包含 description", "description" in node.SCRIPT_PROMPT),
        ("PROMPT_GENERATION_PROMPT 包含 image_prompt", "image_prompt" in node.PROMPT_GENERATION_PROMPT),
        ("PROMPT_GENERATION_PROMPT 包含 end_frame_prompt", "end_frame_prompt" in node.PROMPT_GENERATION_PROMPT),
        ("有 _fix_json_brackets 方法", hasattr(node, '_fix_json_brackets')),
        ("有 _parse_json_objects_individually 方法", hasattr(node, '_parse_json_objects_individually')),
    ]
    
    all_passed = True
    for check_name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"  {status} {check_name}")
        if not passed:
            all_passed = False
    
    return all_passed


async def main():
    print("\n🚀 开始 StoryboardDirector 端到端集成测试...\n")
    
    results = []
    
    results.append(("save_shots Tool", await test_save_shots_tool()))
    results.append(("save_shot_prompts Tool", await test_save_shot_prompts_tool()))
    results.append(("generate_shot_images Tool", await test_generate_shot_images_tool()))
    results.append(("Celery Task 导入", await test_celery_task_import()))
    results.append(("Node 完整流程检查", await test_node_full_flow()))
    
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {status}: {name}")
    
    passed_count = sum(1 for _, p in results if p)
    print(f"\n总计: {passed_count}/{len(results)} 通过")
    
    if passed_count == len(results):
        print("\n✅ 所有端到端测试通过！")
        return 0
    else:
        print("\n❌ 部分测试失败")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
