from google import genai

client = genai.Client()

interaction = client.interactions.create(
    model="gemini-2.5-flash",
    input="what's the BTC price now?",
    tools=[{"type": "google_search"}]
)
# Find the text output (not the GoogleSearchResultContent)
text_output = next((o for o in interaction.outputs if o.type == "text"), None)
if text_output:
    print(text_output.text)