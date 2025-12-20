import os
from google import genai
import pprint # 引入这个库是为了打印得更好看

client = genai.Client()

def inspect_interaction(interaction_id):
    print(f"🔍 正在深度检查 Interaction ID: {interaction_id} ...")
    
    try:
        interaction = client.interactions.get(interaction_id)
        
        print(f"\n✅ 核心状态确认: {interaction.status}")
        print(f"🔗 上一轮 ID: {interaction.previous_interaction_id}")
        print("-" * 50)
        
        print("📦 [对象内部结构解剖]:")
        # 方法 A: 尝试直接打印对象，通常 SDK 会有很好的格式化输出
        print(interaction)
        
        print("-" * 50)
        print("🕵️ [属性列表侦探]:")
        # 方法 B: 打印所有属性名，帮我们找到 'input' 到底变成了什么
        # 比如看看有没有 'inputs', 'history', 'parts' 之类的名字
        attributes = [a for a in dir(interaction) if not a.startswith('_')]
        print(attributes)

    except Exception as e:
        print(f"❌ 发生未知错误: {e}")

# -------------------------------------------------------------------------
# 执行
# -------------------------------------------------------------------------
target_id = 'v1_ChdOaEZHYWNfNEZOenExZThQNXJHSjBBTRIXTmhGR2FjXzRGTnpxMWU4UDVyR0owQU0'

if target_id:
    inspect_interaction(target_id)