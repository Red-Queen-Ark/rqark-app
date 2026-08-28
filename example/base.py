import asyncio
from model import MODEL_NAME
from rqark_app.app import AgentApp, Provider
from rqark_app.agent.agents import AgentHoliday, Diana, Wednesday

provider = Provider(MODEL_NAME, 'api_key', 'http://127.0.0.1:8080', 0, combine=True)

agents = [
    Wednesday(),
    AgentHoliday(), 
    Diana(), 
]

app = AgentApp( [provider], agents)

async def main():
    messages = await app.chat('你好')
    print(messages)

if __name__ == "__main__":
    asyncio.run(main())