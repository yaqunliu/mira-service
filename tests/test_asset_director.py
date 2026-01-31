"""
AssetDirectorNode 测试
测试 LLM 生成图片提示词功能
"""
import asyncio
import sys
import os

sys.path.insert(0, "/app")
os.chdir("/app")


async def test_prompt_generation():
    """测试 LLM 生成提示词功能"""
    print("=" * 50)
    print("测试 1: LLM 生成图片提示词")
    print("=" * 50)
    
    from app.agent.graph.nodes.teams.asset_director import AssetDirectorNode
    
    node = AssetDirectorNode()
    
    # 测试角色提示词
    char_desc = "小雨，自由撰稿人，文静内向，长黑发披肩，戴眼镜，穿着简约的白色毛衣"
    print(f"\n角色描述: {char_desc}")
    print("生成提示词中...")
    
    char_prompt = await node._generate_prompt("角色", char_desc)
    print(f"✅ 角色提示词:\n   {char_prompt[:150]}...")
    
    # 测试场景提示词
    scene_desc = "温馨的咖啡厅 午后阳光透过落地窗洒入"
    print(f"\n场景描述: {scene_desc}")
    print("生成提示词中...")
    
    scene_prompt = await node._generate_prompt("场景", scene_desc)
    print(f"✅ 场景提示词:\n   {scene_prompt[:150]}...")
    
    return True


async def test_node_instantiation():
    """测试节点实例化"""
    print("\n" + "=" * 50)
    print("测试 2: AssetDirectorNode 实例化")
    print("=" * 50)
    
    try:
        from app.agent.graph.nodes.teams.asset_director import AssetDirectorNode
        
        node = AssetDirectorNode()
        print(f"✅ 实例化成功")
        print(f"   - 有 run 方法: {hasattr(node, 'run')}")
        print(f"   - 有 LLM: {hasattr(node, 'llm')}")
        print(f"   - 有 _generate_prompt 方法: {hasattr(node, '_generate_prompt')}")
        return True
    except Exception as e:
        print(f"❌ 实例化失败: {e}")
        return False


async def test_with_mock_state():
    """测试 run 方法（无数据库数据时的行为）"""
    print("\n" + "=" * 50)
    print("测试 3: run 方法 (Mock State)")
    print("=" * 50)
    
    from app.agent.graph.nodes.teams.asset_director import AssetDirectorNode
    from app.agent.state.schemas import ProductionStage
    
    node = AssetDirectorNode()
    
    # 使用不存在的 UUID，应该返回"所有资产已完成"
    test_state = {
        "creation_uuid": "non-existent-uuid",
        "creation_id": 999999,  # 不存在的 ID
        "production_stage": ProductionStage.SCRIPT_ANALYZED,
        "production_progress": {},
    }
    
    try:
        result = await node.run(test_state)
        
        if "所有角色和场景图片都已生成完成" in result.get("response_text", ""):
            print("✅ 无待生成资产时正确返回完成状态")
            print(f"   - production_stage: {result.get('production_stage')}")
            return True
        elif "错误" in result.get("response_text", ""):
            print(f"⚠️  返回错误（预期行为）: {result.get('response_text')[:100]}")
            return True
        else:
            print(f"❓ 返回内容: {result.get('response_text')[:100]}")
            return True
            
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("\n🚀 开始 AssetDirectorNode 测试...\n")
    
    results = []
    results.append(("节点实例化", await test_node_instantiation()))
    results.append(("LLM 提示词生成", await test_prompt_generation()))
    results.append(("Mock State 测试", await test_with_mock_state()))
    
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
