from rqark_core.types.chat import UserMessage

from rqark_app.types.session import ChatMessage


def test_chat_message_to_dict():
    user_msg = UserMessage('test')
    chat_msg = ChatMessage(user_msg)

    data = chat_msg.to_dict()

    assert len(chat_msg.datetime) > 0
    assert data['datetime'] == chat_msg.datetime
