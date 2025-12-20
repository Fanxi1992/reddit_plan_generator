from PIL import Image
from google import genai

client = genai.Client()

image = Image.open("学信网博士学历照片.jpg")
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[image, "Tell me about this guy."],
)
print(response.text)