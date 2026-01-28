#!/usr/bin/env python3
"""
创建测试用的创作项目和文案内容

用于 Agent 测试
"""

import asyncio
import argparse
import httpx
import json
import uuid

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8100
API_BASE_URL = "http://{host}:{port}/api/v1"

USER_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwOi8vMTI3LjAuMC4xOjU0MzIxL2F1dGgvdjEiLCJzdWIiOiJhODUxZmQyNy05OTU0LTQwZmItOWFmMS1mMjY0OWI0N2M3NGIiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzY5NTg5MzIyLCJpYXQiOjE3Njk1ODU3MjIsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZ29vZ2xlIiwicHJvdmlkZXJzIjpbImdvb2dsZSJdfSwidXNlcl9tZXRhZGF0YSI6eyJhdmF0YXJfdXJsIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUNnOG9jSW9ndVdpZUZfQVFwOWl6b1dubnFSRTBVb1BsNmxES3luMWJ4bVdJVnZQZ20zcWgzYz1zOTYtYyIsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmdWxsX25hbWUiOiJ3YW5oZW5nIHpoYW5nIiwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tIiwibmFtZSI6IndhbmhlbmcgemhhbmciLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInBpY3R1cmUiOiJodHRwczovL2xoMy5nb29nbGV1c2VyY29udGVudC5jb20vYS9BQ2c4b2NJb2d1V2llRl9BUXA5aXpvV25ucVJFMFVvUGw2bERLeW4xYnhtV0lWdlBnbTNxaDNjPXM5Ni1jIiwicHJvdmlkZXJfaWQiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMiLCJzdWIiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMifSwicm9sZSI6ImF1dGhlbnRpY2F0ZWQiLCJhYWwiOiJhYWwxIiwiYW1yIjpbeyJtZXRob2QiOiJvYXV0aCIsInRpbWVzdGFtcCI6MTc2OTM5OTY2OH1dLCJzZXNzaW9uX2lkIjoiNTNhYmIwNDYtNDJiMy00ZTEzLTgyNmUtMjAxNGM5NmZlMmQ4IiwiaXNfYW5vbnltb3VzIjpmYWxzZX0.E242Cp4MTzDONULroHGS5UVbA4kYLh5GkymNCEI2j1Q"


SCRIPT_CONTENT = """场景：1. 喧闹的鱼市 - 白天

【动作行】
阳光穿过充满鱼腥味的雾气。鱼摊旁的泡沫箱堆里，橘猫阿九正瘫坐着。它穿着一件油腻的灰色亚麻短衫，肚子上的肥肉把中间两个扣子崩得死死的。它用那双肥厚、踩着破草鞋的小脚丫有节奏地拍打着地面，腰间的草绳里插着一把毫不起眼的断头竹木剑。

【桥段应用：隐藏身份/扫地僧】
—— 谁能想到，这根用来剔牙都嫌粗的竹木剑，曾是御猫堂的镇派至宝？

【动作行】
狸花猫老王挥动着那把巨大的生锈切鱼刀，"砰"的一声剁掉一颗鱼头。他推了推破损的圆框老花镜，斜眼看着阿九。

老王
"阿九，隔壁王寡妇家的猫都去抓老鼠了，你倒好，天天在这'呆呆地'地对着鱼摊发呆？"

阿九
（【对白风格：贱萌型】）
"老王，这你就不懂了。我这不是发呆，是'先欠着'。等我攒够了人品，这整条街的鱼都是我的。再说，抓老鼠多累啊，有损我这高贵的颜值，略略略。"

【动作行】
沉重的脚步声传来。身高近两米的杜宾犬头领带着两名跟班闯入。他穿着黑色机车皮背心，肌肉将皮衣撑得几乎炸裂，手里的粗木棍缠满了带血的铁丝。

杜宾犬头领
（用棍子敲打着阿九的草鞋，低吼）
"胖子，听说这片鱼市你说了算？把那块深海金枪鱼交出来，不然把你这一身肥油榨出来点灯。"

【动作行】
阿九慢慢直起腰，肥硕的身躯在杜宾犬面前显得滑稽又渺小。它抠了抠耳朵，露出了一个经典的、极其魔性的表情。

【桥段应用：这谁顶得住/贱萌型】
阿九
（贱兮兮地，用小短指点着对方的铆钉项圈）
"哎哟喂，宝贝儿，你这项圈挺别致啊，是拼夕夕九块九包邮的吗？你说你长得像个意外，说话的样子却真的很努力在思考，这真让我感动，呜呜呜。"

【动作行】
杜宾犬暴怒，挥起缠铁丝的木棍猛砸而下！
【桥段应用：轻松化解致命一击/动作追逐】

【动作行】
阿九并没有逃跑，而是双腿一蹬，肥硕的身躯竟然像弹球一样灵活。它的小草鞋在湿滑的地面一蹭，整只猫以一种不可思议的角度滑过杜宾犬的胯下，顺势解开了腰间的草绳。

【动作行】
"啪！"草绳精准地勾住了上方的鱼秤，巨大的秤砣由于惯性飞出，正好砸在三只恶犬撞在一起的脑门上。
阿九在空中一个灵巧的翻滚，稳稳落在墙头，手里已经顺走了一块上好的鱼腹肉。

阿九
（【对白风格：毒舌型】）
"如果你那核桃大小的大脑能稍微运作一下，也不至于想出这种连单细胞生物都觉得愚蠢的突袭计划。"

【动作行】
阿九低头，看到墙角里，穿着破烂粉色小裙子的狮子猫小白正缩成一团，蓝黄双色瞳孔里满是泪水。
【对白风格：温柔治愈型】
阿九
（声音突然变得极其温柔，递过鱼肉）
"别怕，我在呢。慢慢来，先把这块鱼吃了，一切都会好起来的。"

【动作行】
夕阳下，阿九挺直了腰杆，灰色短衫被风吹动。他脖子上那块断剑吊坠熠熠生辉。

【桥段应用：身份线索猜测/绝技反差】
阿九
（【对白风格：冷峻型】，握住了腰间的断头竹木剑）
"既然敢动我的人……那就准备好付出代价。"

【动作行】
远处房顶，黑色孟买猫神秘人正紧了紧身上的紫色斗篷，子母双剑在夜行服后若隐若现。

神秘人
（金色的瞳孔收缩）
"那种步法……果然是他。御猫堂最凶狠的'九命残剑'。"
"""


class TestSetup:
    def __init__(self, host: str, port: int, token: str):
        self.base_url = API_BASE_URL.format(host=host, port=port)
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.client = httpx.AsyncClient(timeout=30.0)
        self.user_info = None
    
    async def close(self):
        await self.client.aclose()
    
    async def get_user_info(self) -> dict:
        """获取当前用户信息"""
        url = f"{self.base_url}/users/me"
        response = await self.client.get(url, headers=self.headers)
        if response.status_code == 200:
            self.user_info = response.json()
            print(f"✅ 获取用户信息成功: user_id={self.user_info.get('user_id')}")
            return self.user_info
        else:
            print(f"❌ 获取用户信息失败: {response.status_code}")
            return None
    
    async def get_user_uuid(self) -> str:
        """获取用户的 UUID (sub)"""
        if not self.user_info:
            await self.get_user_info()
        return self.user_info.get("sub") if self.user_info else None
    
    async def create_creation(self, title: str, script_content: str) -> dict:
        """创建创作项目和文案"""
        user_uuid = await self.get_user_uuid()
        if not user_uuid:
            raise Exception("无法获取用户信息")
        
        # 1. 创建 Creation
        creation_uuid = str(uuid.uuid4())
        creation_url = f"{self.base_url}/creations"
        creation_payload = {
            "uuid": creation_uuid,
            "title": title,
            "type": "script",
            "owner_id": self.user_info.get("user_id")
        }
        
        print(f"\n{'='*60}")
        print("📝 创建创作项目")
        print(f"URL: {creation_url}")
        print(f"数据: {json.dumps(creation_payload, ensure_ascii=False)}")
        print(f"{'='*60}")
        
        creation_response = await self.client.post(creation_url, json=creation_payload, headers=self.headers)
        print(f"Creation 状态码: {creation_response.status_code}")
        if creation_response.status_code not in [200, 201]:
            print(f"Creation 响应: {creation_response.text}")
        
        # 2. 创建 Script
        script_uuid = str(uuid.uuid4())
        script_url = f"{self.base_url}/scripts"
        script_payload = {
            "uuid": script_uuid,
            "title": f"{title} - 剧本",
            "content": script_content,
            "creation_uuid": creation_uuid
        }
        
        print(f"\n{'='*60}")
        print("📝 创建剧本")
        print(f"URL: {script_url}")
        print(f"数据: {json.dumps(script_payload, ensure_ascii=False)[:500]}...")
        print(f"{'='*60}")
        
        script_response = await self.client.post(script_url, json=script_payload, headers=self.headers)
        print(f"Script 状态码: {script_response.status_code}")
        if script_response.status_code not in [200, 201]:
            print(f"Script 响应: {script_response.text}")
        
        return {
            "creation_uuid": creation_uuid,
            "script_uuid": script_uuid,
            "title": title
        }


async def main():
    parser = argparse.ArgumentParser(description="创建测试创作项目")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST, help=f"服务器地址")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"端口号")
    parser.add_argument("--token", type=str, default=USER_TOKEN, help="JWT Token")
    
    args = parser.parse_args()
    
    setup = TestSetup(args.host, args.port, args.token)
    
    try:
        # 获取用户信息
        await setup.get_user_info()
        
        # 创建创作项目
        result = await setup.create_creation(
            title="橘猫阿九：鱼市风云",
            script_content=SCRIPT_CONTENT
        )
        
        print(f"\n{'='*60}")
        print("✅ 测试创作项目创建成功！")
        print(f"{'='*60}")
        print(f"\n📋 项目信息:")
        print(f"  - 创作项目 UUID: {result['creation_uuid']}")
        print(f"  - 剧本 UUID: {result['script_uuid']}")
        print(f"  - 标题: {result['title']}")
        
        print(f"\n🚀 测试 Agent:")
        print(f"  python test_agent.py --creation-uuid {result['creation_uuid']}")
        
    except Exception as e:
        print(f"\n❌ 创建失败: {e}")
    finally:
        await setup.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n被用户中断")
    except Exception as e:
        print(f"\n失败: {e}")
