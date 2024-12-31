import os
import json

# in dev include icecream for easier/faster debug with code name(.py) & line numbers:
# from icecream import ic
# ic.configureOutput(includeContext=True, contextAbsPath=True)

class UserSession:

	def __init__(self):
		self.app_version = "2025.01.1.0" # keep user_*'s up-to-date
		# 14 days duration in seconds before refresh user's google SSO signin:
		self.signin_timeout = 1209600 
		self.client_ip = None # important
		self.users_google_sub = None # important
		self.sambuca = None # important
		self.path_to_settings = None # important
		self.session_id = None
		self.session_cookie = None

		# from this list, determine which providers are available for user's session:
		self.providers = [
			"Keys2Text", "Anthropic", "Google", "Groq", "LMStudio",
			"Ollama", "OpenAI", "OpenRouter", "DuckDuckGo"
		]

		self.ui_page = None
		self.splash_dialog = None
		self.splashed = False
		self.total_models = 0
		self.saved_chat_histories = []
		self.chat_history = ""
		self.send_button = None
		self.thinking_label = None
		self.abort_stream = None
		self.abort = False
		self.chunks = ""
		self.start_time = None
		self.message_container = None
		self.response_message = None
		self.ui_select_provider = None
		self.provider = None
		self.ui_select_model = None
		self.model = ""
		self.ui_button_temp = None
		self.ui_knob_temp = None
		self.duckduckgo_vqd = None
		self.openai_compat_models_endpoint = "/v1/models"
		self.openai_compat_chat_endpoint = "/v1/chat/completions"

