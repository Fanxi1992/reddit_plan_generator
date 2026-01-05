from google import genai

client = genai.Client()
chat = client.chats.create(model="gemini-3-flash-preview")

response = chat.send_message("我的硕士专业是西南交通大学的土木工程")
print(response.text)

response = chat.send_message("可是我2018年转行了，因为我感觉土木不行了，事实情况也是如此，你赞同吗？")
print(response.text)

for message in chat.get_history():
    print(f'role - {message.role}',end=": ")
    print(message.parts[0].text)