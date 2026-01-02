from google import genai

client = genai.Client()

interaction =  client.interactions.create(
    model="gemini-3-pro-preview",
    input="Tell me a short joke about programming."
)

print(interaction.outputs[-1].text)