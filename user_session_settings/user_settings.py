#####################################################
# WARNING changing any of this makes all user's     #
#         .json files invalid                       #
#####################################################
import os
import json

import base64
import hmac
import hashlib
from dotenv import load_dotenv
from cryptography.fernet import Fernet

# in dev include icecream for easier/faster debug with code name(.py) & line numbers:
# from icecream import ic
# ic.configureOutput(includeContext=True, contextAbsPath=True)

class UserSettings:

	def __init__(self):
		#                   year.mo.ver
		self.app_version = "2025.01.1.0"
		self.signin_time = 0
		self.users_google_sub = None # important
		self.path_to_settings = None # important
		self.google_picture = None
		self.google_given_name = None
		self.google_family_name = None
		self.google_email = None
		self.google_email_verified = None
		self.session_id = None
		self.session_cookie = None
		self.websocket_name = None

		self.settings_updated = False
		self.settings_response = None # includes: redirect url and settings cookies
		self.darkness = None
		self.current_primary_color = '#4CAF50' # green-ish
		self.eight_providers = '''
			1. OpenAI : GPT+o1s - full tilt bozo<br>
			2. Anthropic : Claudes - c’est moi<br>
			3. Google : Geminis - hot mess<br>
			4. Groq : warp speed engaged<br>
			5. OpenRouter : henny penny<br>
			6. DuckDuckGo : ayup, me ducks<br>
			7. LMStudio : as you like it<br>
			8. Ollama : Metas - hum baa<br>
		'''
		self._default_providers = [
			"Keys2Text", "Anthropic", "Google", "Groq", "LMStudio",
			"Ollama", "OpenAI", "OpenRouter", "DuckDuckGo"
		]
		self.provider_models = {}
		self.provider_settings = {
			"Anthropic": {"api_key": "", "max_tokens": 4096, "timeout": 30},
			"Google": {"api_key": "", "timeout": 30},
			"Groq": {"api_key": "", "timeout": 30},
			"LMStudio": {"api_key": "lmstudio", "base_url": "http://127.0.0.1:5506", "timeout": 30},
			"Ollama": {"api_key": "ollama", "base_url": "http://127.0.0.1:11434", "timeout": 30},
			"OpenAI": {"api_key": "", "timeout": 30},
			"OpenRouter": {"api_key": "", "base_url": "https://openrouter.ai/api/v1", "timeout": 30},
			"DuckDuckGo": {"api_key": "", "base_url": "https://duckduckgo.com/duckchat/v1/chat", "timeout": 30},
		}

	def derive_user_key(self, sambuca):
	    if not isinstance(self.users_google_sub, str):
	        raise ValueError('users_google_sub must be a string')
	    # combine users_google_sub with the master key to derive a unique user key
	    combined_key_material = f"{self.users_google_sub}:{sambuca._signing_key}".encode()
	    h = hmac.new(sambuca._signing_key, combined_key_material, hashlib.sha256)
	    user_key = base64.urlsafe_b64encode(h.digest())
	    return user_key

	def encrypt_data(self, data_to_encrypt, sambuca):
	    user_key = self.derive_user_key(sambuca)
	    fernet = Fernet(user_key)
	    encrypted_data = fernet.encrypt(data_to_encrypt.encode())
	    encrypted_data_hex = encrypted_data.hex()
	    return encrypted_data_hex

	def decrypt_data(self, encrypted_data_hex, sambuca):
	    user_key = self.derive_user_key(sambuca)
	    fernet = Fernet(user_key)
	    encrypted_data = bytes.fromhex(encrypted_data_hex)
	    decrypted_data = fernet.decrypt(encrypted_data)
	    return decrypted_data.decode()

	def update_from_dict(self, data):
		for key, value in data.items():
			if hasattr(self, key):
				current_value = getattr(self, key)
				# if the current attribute is a dictionary, 
				# and the incoming value is also a dictionary, 
				# update recursively
				if isinstance(current_value, dict) and isinstance(value, dict):
					self._update_nested_dict(current_value, value)
				else:
					setattr(self, key, value)

	def _update_nested_dict(self, target, updates):
		for key, value in updates.items():
			if key in target and isinstance(target[key], dict) and isinstance(value, dict):
				self._update_nested_dict(target[key], value)
			else:
				target[key] = value

	def to_dict(self):
		return self.__dict__

	def to_json(self):
		return json.dumps(self.to_dict())

	def to_indented_json(self):
		return json.dumps(self.to_dict(), indent=2)

	def load_from_json_file(self, user_session):
	    try:
	        if os.path.exists(self.path_to_settings):
	            with open(self.path_to_settings, 'r') as json_file:
	                # Read the encrypted data from the file
	                encrypted_data = json.load(json_file)
	                # Decrypt the data
	                decrypted_data = self.decrypt_data(encrypted_data, user_session.sambuca)
	                # Parse the decrypted data as JSON
	                if isinstance(decrypted_data, str):  # Ensure it's a string before parsing
	                    data = json.loads(decrypted_data)
	                else:
	                    data = decrypted_data  # Already parsed (unlikely but safe)
	                # Update the object's settings
	                self.update_from_dict(data)
	        else:
	            # No .json file found, so create one using default settings
	            self.save_as_json_file(user_session)
	    except Exception as e:
	        ic("An error occurred in: load_from_json_file:", e)
	        pass  # start with defaults

	def save_as_json_file(self, user_session):
		# Tue Nov 26, 2024 works on Render.com's persistent storage, 
		# but to use the same code on mac must do:
		#   cd /var
		#   sudo mkdir data
		#   cd ..
		#   sudo chmod 777 /var/data
		# ... now it works the same as Render.com
		# note: along with encryption this should avoid all of the 
		#       the request/response cookies stuff, and will
		#       be just as secure/individual/session based in 
		#       conjunction with google's SSO 'sub' as user id,
		#       and the .json filename will be 'sub'
		try:
			with open(self.path_to_settings, 'w') as json_file:
				encrypted_data_hex = self.encrypt_data(self.to_json(), user_session.sambuca)
				# print(f'Encrypted Data (Hex): {encrypted_data_hex}')
				# json.dump(self.to_json(), json_file)
				json.dump(encrypted_data_hex, json_file)
		except Exception as e:
			print("An error occurred in: save_as_json_file:", e)
			pass

	def get_provider_setting(self, provider_name, key):
		if provider_name in self.provider_settings:
			return self.provider_settings[provider_name][key]
		return ""

	def set_provider_setting(self, provider_name, key, value, response):
		self.provider_settings[provider_name][key] = value
		# self.encrypt_settings('PROVIDER_SETTINGS', response)

	@property
	def providers(self):
		# don't allow providers to be changed
		return self._default_providers.copy()

