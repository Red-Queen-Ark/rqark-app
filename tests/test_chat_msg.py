from rqark_core.types.chat import UserMessage
from rqark_app.types.session import ChatMessage

user_msg = UserMessage('test')
chat_msg = ChatMessage(user_msg)

print(chat_msg.to_dict())
assert len(chat_msg.datetime) > 0