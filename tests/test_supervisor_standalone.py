#!/usr/bin/env python3
"""
Supervisor 架构独立测试脚本

不依赖完整项目环境，直接测试核心逻辑
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_tools_import():
    """测试工具导入"""
    print("=" * 50)
    print("测试 1: 工具导入")
    print("=" * 50)
    
    try:
        from app.agent.tools.regenerate_tools import (
            clear_asset, submit_generation, regenerate, clear_all, REGENERATE_TOOLS
        )
        print(f"✅ regenerate_tools: {len(REGENERATE_TOOLS)} 个工具")
        
        from app.agent.tools.version_tools import (
            get_version_history, restore_version, VERSION_TOOLS
        )
        print(f"✅ version_tools: {len(VERSION_TOOLS)} 个工具")
        
        from app.agent.tools.context_tools import (
            get_script_context, get_adjacent_shots, check_constraints, CONTEXT_TOOLS
        )
        print(f"✅ context_tools: {len(CONTEXT_TOOLS)} 个工具")
        
        return True
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_supervisor_node_import():
    """测试 Supervisor Node 导入"""
    print("\n" + "=" * 50)
    print("测试 2: Supervisor Node 导入")
    print("=" * 50)
    
    try:
        from app.agent.graph.nodes.supervisor import (
            supervisor_node,
            route_from_supervisor,
            _get_supervisor_tools,
        )
        
        tools = _get_supervisor_tools()
        tool_names = [t.name for t in tools]
        
        print(f"✅ supervisor_node 导入成功")
        print(f"✅ route_from_supervisor 导入成功")
        print(f"✅ Supervisor 工具: {tool_names}")
        
        return True
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_route_to_worker():
    """测试 route_to_worker 工具"""
    print("\n" + "=" * 50)
    print("测试 3: route_to_worker 工具")
    print("=" * 50)
    
    try:
        from app.agent.graph.nodes.supervisor import route_to_worker
        
        # 测试有效 Worker
        result = await route_to_worker.ainvoke({
            "worker": "script_analyst",
            "task": "分析剧本",
        })
        
        if result["success"]:
            print(f"✅ route_to_worker(script_analyst): {result}")
        else:
            print(f"❌ route_to_worker 失败: {result}")
            return False
        
        # 测试无效 Worker
        result = await route_to_worker.ainvoke({
            "worker": "invalid",
            "task": "测试",
        })
        
        if not result["success"]:
            print(f"✅ route_to_worker(invalid) 正确返回错误")
        else:
            print(f"❌ route_to_worker(invalid) 应该失败")
            return False
        
        return True
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_route_from_supervisor():
    """测试 Supervisor 路由函数"""
    print("\n" + "=" * 50)
    print("测试 4: route_from_supervisor 路由")
    print("=" * 50)
    
    try:
        from app.agent.graph.nodes.supervisor import route_from_supervisor
        
        # 测试路由到 Worker
        state = {"next_worker": "script_analyst", "needs_input": False}
        result = route_from_supervisor(state)
        assert result == "script_analysis", f"期望 script_analysis, 得到 {result}"
        print(f"✅ next_worker=script_analyst → {result}")
        
        # 测试 asset_designer
        state = {"next_worker": "asset_designer", "needs_input": False}
        result = route_from_supervisor(state)
        assert result == "asset_generation", f"期望 asset_generation, 得到 {result}"
        print(f"✅ next_worker=asset_designer → {result}")
        
        # 测试需要用户输入
        state = {"next_worker": "script_analyst", "needs_input": True}
        result = route_from_supervisor(state)
        assert result == "return_to_main", f"期望 return_to_main, 得到 {result}"
        print(f"✅ needs_input=True → {result}")
        
        # 测试无 Worker
        state = {"next_worker": None, "needs_input": False}
        result = route_from_supervisor(state)
        assert result == "stage_complete", f"期望 stage_complete, 得到 {result}"
        print(f"✅ next_worker=None → {result}")
        
        return True
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_subgraph_build():
    """测试子图构建"""
    print("\n" + "=" * 50)
    print("测试 5: 子图构建")
    print("=" * 50)
    
    try:
        from app.agent.graph.comic_drama_subgraph import (
            build_comic_drama_subgraph,
            USE_SUPERVISOR_MODE,
        )
        
        print(f"   USE_SUPERVISOR_MODE = {USE_SUPERVISOR_MODE}")
        
        subgraph = build_comic_drama_subgraph()
        print(f"✅ 子图构建成功: {type(subgraph)}")
        
        return True
    except Exception as e:
        print(f"❌ 子图构建失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_state_schema():
    """测试 State Schema 更新"""
    print("\n" + "=" * 50)
    print("测试 6: State Schema")
    print("=" * 50)
    
    try:
        from app.agent.state.schemas import ComicDramaState
        
        # 检查新字段
        annotations = ComicDramaState.__annotations__
        
        new_fields = ["production_cache", "next_worker", "needs_input"]
        for field in new_fields:
            if field in annotations:
                print(f"✅ {field}: {annotations[field]}")
            else:
                print(f"❌ {field} 字段缺失")
                return False
        
        return True
    except Exception as e:
        print(f"❌ Schema 检查失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("\n🚀 开始 Supervisor 架构测试...\n")
    
    results = []
    results.append(("工具导入", await test_tools_import()))
    results.append(("Supervisor Node 导入", await test_supervisor_node_import()))
    results.append(("route_to_worker", await test_route_to_worker()))
    results.append(("route_from_supervisor", await test_route_from_supervisor()))
    results.append(("子图构建", await test_subgraph_build()))
    results.append(("State Schema", await test_state_schema()))
    
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
