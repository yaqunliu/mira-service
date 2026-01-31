"""
Subgraph 集成测试脚本
直接测试各节点的 import 和基本功能
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, "/app")
os.chdir("/app")

async def test_imports():
    """测试所有团队节点是否能正常导入"""
    print("=" * 50)
    print("测试 1: 导入团队节点")
    print("=" * 50)
    
    try:
        from app.agent.graph.nodes.teams import (
            ScriptAnalystNode,
            AssetDirectorNode,
            StoryboardDirectorNode,
            AudioEngineerNode,
            VideoEditorNode,
            FinalEditorNode,
        )
        print("✅ ScriptAnalystNode 导入成功")
        print("✅ AssetDirectorNode 导入成功")
        print("✅ StoryboardDirectorNode 导入成功")
        print("✅ AudioEngineerNode 导入成功")
        print("✅ VideoEditorNode 导入成功")
        print("✅ FinalEditorNode 导入成功")
        return True
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False


async def test_subgraph_build():
    """测试 subgraph 是否能正常构建"""
    print("\n" + "=" * 50)
    print("测试 2: 构建 Subgraph")
    print("=" * 50)
    
    try:
        from app.agent.graph.comic_drama_subgraph import build_comic_drama_subgraph
        subgraph = build_comic_drama_subgraph()
        print(f"✅ Subgraph 构建成功")
        print(f"   - 类型: {type(subgraph)}")
        return True
    except Exception as e:
        print(f"❌ Subgraph 构建失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_script_analyst():
    """测试 ScriptAnalystNode 实例化"""
    print("\n" + "=" * 50)
    print("测试 3: ScriptAnalystNode 实例化")
    print("=" * 50)
    
    try:
        from app.agent.graph.nodes.teams.script_analyst import ScriptAnalystNode
        node = ScriptAnalystNode()
        print(f"✅ ScriptAnalystNode 实例化成功")
        print(f"   - 有 run 方法: {hasattr(node, 'run')}")
        print(f"   - 有 LLM: {hasattr(node, 'llm')}")
        return True
    except Exception as e:
        print(f"❌ ScriptAnalystNode 实例化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_stage_router():
    """测试 stage_router_node"""
    print("\n" + "=" * 50)
    print("测试 4: Stage Router")
    print("=" * 50)
    
    try:
        from app.agent.graph.comic_drama_subgraph import stage_router_node
        from app.agent.state.schemas import ProductionStage
        
        test_state = {
            "creation_uuid": "test-uuid",
            "production_stage": ProductionStage.INIT,
            "user_intent": "analyze_script",
            "script_text": "测试剧本",
        }
        
        result = await stage_router_node(test_state)
        print(f"✅ stage_router_node 执行成功")
        print(f"   - target_stage: {result.get('target_stage')}")
        return True
    except Exception as e:
        print(f"❌ stage_router_node 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("\n🚀 开始 Subgraph 集成测试...\n")
    
    results = []
    results.append(("导入团队节点", await test_imports()))
    results.append(("构建 Subgraph", await test_subgraph_build()))
    results.append(("ScriptAnalystNode", await test_script_analyst()))
    results.append(("Stage Router", await test_stage_router()))
    
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {status}: {name}")
    
    print(f"\n总计: {passed}/{total} 通过")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
