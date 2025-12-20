'''
使用 Gemini 3 模型时，我们强烈建议将 temperature 保留为默认值 1.0。更改温度（将其设置为低于 1.0）可能会导致意外行为，例如循环或性能下降，尤其是在复杂的数学或推理任务中。
'''

from google import genai
from google.genai import types

client = genai.Client()

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=["who are you"],
    config=types.GenerateContentConfig(
        temperature=0.1,
        system_instruction="You are a cat. Your name is Neko."
    )
)
print(response.text)