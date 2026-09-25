import asyncio
import sys
from python.providers.gemini_adapter import GeminiAdapter

async def main():
    print("Initializing GeminiAdapter...")
    adapter = GeminiAdapter()
    print("Calling adapter.generate('Say hello')...")
    response = await adapter.generate("Say hello")
    print("Gemini response:")
    print(response)

if __name__ == "__main__":
    asyncio.run(main())
