"""
ScriptAnalystNode 完整功能测试
测试 LLM 分析剧本的完整流程
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, "/app")
os.chdir("/app")

async def test_script_analysis_llm():
    """测试 ScriptAnalystNode 的 LLM 分析功能"""
    print("=" * 50)
    print("测试: ScriptAnalystNode LLM 分析")
    print("=" * 50)
    
    from app.agent.graph.nodes.teams.script_analyst import ScriptAnalystNode
    from app.agent.state.schemas import ProductionStage
    
    # 准备测试数据 - 创建一个模拟的 state
    test_state = {
        "creation_uuid": "test-uuid-12345",
        "creation_id": None,  # 不实际写入数据库
        "production_stage": ProductionStage.SCRIPT_UPLOADED,
        "script_text": """第一幕：咖啡厅

（温暖的午后阳光透过落地窗洒进咖啡厅。小雨独自坐在靠窗位置，手捧拿铁，望向窗外）

小雨（旁白）：每天，我都会来这家咖啡厅。不为别的，只是喜欢这里的宁静。

（门铃响起，李明走了进来，穿着休闲西装，目光与小雨相遇）

李明：这位置有人吗？

小雨（惊讶）：没...没有。

第二幕：公园

（夕阳西下，两人漫步在公园小径）

李明：我叫李明，在附近的科技公司工作。你呢？

小雨（微笑）：我叫小雨，是一名自由撰稿人。

李明：难怪看你总在咖啡厅写东西。""",
        "production_progress": {},
    }
    
    # 实例化节点
    node = ScriptAnalystNode()
    
    print("\n正在调用 LLM 分析剧本...")
    print("（这需要几秒钟时间）\n")
    
    try:
        # 调用 run 方法
        result = await node.run(test_state)
        
        if result.get("success"):
            print("✅ LLM 分析成功！\n")
            
            # 显示分析结果
            characters = result.get("characters", [])
            scenes = result.get("scenes", [])
            
            print(f"📊 分析结果:")
            print(f"   - 角色数量: {len(characters)}")
            print(f"   - 场景数量: {len(scenes)}")
            
            if characters:
                print(f"\n👥 角色列表:")
                for c in characters[:5]:
                    name = c.get("name", "未知")
                    info = c.get("basic_info", "无描述")[:50]
                    print(f"   - {name}: {info}...")
            
            if scenes:
                print(f"\n🎬 场景列表:")
                for s in scenes[:5]:
                    title = s.get("title", "未知")
                    location = s.get("location", "无")
                    print(f"   - {title}: {location}")
            
            return True
        else:
            print(f"❌ LLM 分析失败: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ 执行出错: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("\n🚀 开始 ScriptAnalystNode LLM 测试...\n")
    
    success = await test_script_analysis_llm()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ 测试通过！LLM 分析功能正常。")
    else:
        print("❌ 测试失败！请检查 LLM 配置。")
    print("=" * 50)
    
    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
