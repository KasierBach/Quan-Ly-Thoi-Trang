from app import create_app
from app.services.conversation_service import ConversationService
import json

app = create_app()
with app.app_context():
    # Try to get conversations for user 1 (Admin usually)
    try:
        convs = ConversationService.get_user_conversations(1)
        print(json.dumps(convs, indent=2, default=str))
    except Exception as e:
        print(f"ERROR: {e}")
