import os
import platform
import sys
import signal
import traceback
import uuid
import html
import re
from datetime import datetime
import time

import asyncio
import json

import httpx

from fastapi.responses import JSONResponse, RedirectResponse
from fastapi import HTTPException, Request, Depends, status, WebSocket, WebSocketDisconnect
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from nicegui import app, ui, run, Client, events
from nicegui import __version__ as nv

from openai import OpenAI

import google.generativeai as genai
from google.generativeai.types import GenerationConfig
from google.generativeai.types import HarmBlockThreshold

import anthropic

from groq import Groq
from groq import AsyncGroq

from openai import __version__ as oav
from anthropic import __version__ as av
from google.generativeai import __version__ as ggv
from groq import __version__ as gv
# from ollama import __version__ as ov

from importlib.metadata import version, PackageNotFoundError

# from icecream import ic
# ic.configureOutput(includeContext=True, contextAbsPath=True)

import psutil
import gc

# from memory_profiler import print_top_allocations


def print_memory_usage():
	# print_top_allocations()
	process = psutil.Process()
	memory_info = process.memory_info()
	memory_usage_mb = memory_info.rss / (1024 * 1024)
	mum = f"Memory usage: {memory_usage_mb:.2f} MB"
	return mum

# get a list of all objects tracked by the garbage collector
# all_objects = gc.get_objects()
# print(len(all_objects))
# gc.collect()
# all_objects = gc.get_objects()
# print(len(all_objects))


async def keys2text(request: Request, client, ui, user_session, user_settings) -> None:
	ui.add_body_html('''
	<script>
		async function listModels(url, apiKey) {
			try {
				console.log(`${url}`);
				console.log(apiKey);
				const response = await fetch(`${url}`, {
					method: 'GET',
					headers: {
						'Authorization': `Bearer ${apiKey}`,
						'Content-Type': 'application/json'
					}
				});

				if (!response.ok) {
					// this isn't really an error, as Ollama or LM Studio may
					// not be available on the user's computer; so ignore it:
					// console.error(`Error: ${response.status} - ${response.statusText}`);
					return null;
				}

				const models = await response.json();
				console.log(models);
				return models;
			} catch (error) {
				// console.error("Failed to fetch models:", error);
				return null;
			}
		}


		// handle Ollama and LMStudio weirdness:
		async function localStreamChat(websocketName, url, apiKey, model, prompt) {
			let chunks_socket;
			let retries = 0;
			const maxRetries = 1;
			const retryDelay = 300;
			const requestBody = {
				messages: [{ role: 'user', content: prompt }],
				model: model,
				stream: true
			};

			const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
			const host = window.location.host;
			const wsUrl = `${protocol}//${host}${websocketName}`;
			console.log('Connecting to:', wsUrl);

			function connect() {
				chunks_socket = new WebSocket(wsUrl);
				
				chunks_socket.onopen = () => { 
					console.log('WebSocket connected');
					retries = 0;
				};

				chunks_socket.onclose = (event) => {
					console.log('WebSocket closed:', event.code, event.reason);
					if (retries < maxRetries && event.code !== 1000) {
						retries++;
						console.log('Retrying connection, attempt:', retries);
						setTimeout(connect, retryDelay);
					}
				};

				chunks_socket.onerror = (error) => {
					console.log('WebSocket error:', error);
					if (retries < maxRetries) {
						retries++;
						console.log('Retrying after error, attempt:', retries);
						setTimeout(connect, retryDelay);
					}
				};

				return new Promise((resolve) => {
					chunks_socket.addEventListener('open', () => resolve(chunks_socket));
				});
			}

			function sendMessageWithRetry(ws, message, maxAttempts = 3) {
				let attempts = 0;
				const tryToSend = () => {
					if (ws && ws.readyState === WebSocket.OPEN) {
						ws.send(JSON.stringify({ message }));
						return true;
					} else if (attempts < maxAttempts) {
						attempts++;
						setTimeout(tryToSend, 100);
						return false;
					}
					console.error('Failed to send after', maxAttempts, 'attempts');
					return false;
				};
				return tryToSend();
			}

			await connect();

			try {
				const response = await fetch(url, {
					method: 'POST',
					headers: {
						'Content-Type': 'application/json',
						'Authorization': 'Bearer ' + apiKey
					},
					body: JSON.stringify(requestBody)
				});

				if (!response.ok) {
					if (chunks_socket && chunks_socket.readyState === WebSocket.OPEN) {
						chunks_socket.send(JSON.stringify({ message: `HTTP error! Status: ${response.status}` }));
					}
					return;
				}

				const reader = response.body.getReader();
				const decoder = new TextDecoder();

				while (true) {
					const { done, value } = await reader.read();
					if (done) {
						if (chunks_socket && chunks_socket.readyState === WebSocket.OPEN) {
							chunks_socket.send(JSON.stringify({ message: '<<FIN_LOCAL>>' }));
						}
						break;
					}

					const chunk = decoder.decode(value);
					const lines = chunk.split('\\n');

					for (const line of lines) {
						if (line.startsWith('data: ')) {
							try {
								const jsonStr = line.slice(6).trim();
								if (jsonStr && jsonStr !== '[DONE]') {
									const parsedData = JSON.parse(jsonStr);
									if (parsedData.choices && 
										parsedData.choices[0].delta && 
										parsedData.choices[0].delta.content) {
										sendMessageWithRetry(chunks_socket, parsedData.choices[0].delta.content);
									}
								}
							} catch (parseError) {
								console.error('Parse error:', parseError);
								if (chunks_socket && chunks_socket.readyState === WebSocket.OPEN) {
									chunks_socket.send(JSON.stringify({ message: `Parse error: ${parseError.message}` }));
								}
							}
						}
					}
				}
				
				console.log('Stream complete, closing connection');
				if (chunks_socket && chunks_socket.readyState === WebSocket.OPEN) {
					chunks_socket.close(1000, "Normal Closure");
				}

			} catch (error) {
				console.error('Stream error:', error);
				if (chunks_socket && chunks_socket.readyState === WebSocket.OPEN) {
					chunks_socket.send(JSON.stringify({ message: `Stream error: ${error.message}` }));
					chunks_socket.close(1000, "Normal Closure");
				}
			}
		}

		function copyToClipboard(meId, aiId) {
			const meElement = document.getElementById(`c${meId}`);
			const aiElement = document.getElementById(`c${aiId}`);
			let text = "";
			if (meElement) {
				text += meElement.innerText;
			}
			if (aiElement) {
				text += aiElement.innerText;
			}

			// to avoid having to edit (find/replace), remove most Markdown in AI responses:
			let clipText = "";
			const lines = text.split("\\n");
			const filteredLines = lines
				.map(line => {
					const cleanedLine = line.replace(/(\*\*|##|###)/g, "").trim();
					return cleanedLine === "AI:" ? "\\n" + cleanedLine : cleanedLine;
				})
				.filter(line => line !== "content_paste");
			const textWithoutMarkdownAndContentPaste = filteredLines.join("\\n") + "\\n";
			clipText = textWithoutMarkdownAndContentPaste;

			navigator.clipboard.writeText(clipText)
				.then(() => console.log("chat copied to clipboard"))
				.catch(err => console.error("failed to copy chat: ", err));
		}
	</script>
	''')

	# claude's:
	# const filtered_lines = text.split('\n')
	# .filter(line => line.replace(/\*\*|##|###/g, '').trim() !== 'content_paste')
	# .map(line => {
	#   const cleaned = line.replace(/\*\*|##|###/g, '').trim();
	#   return (cleaned === 'AI:' ? '\n' + cleaned : cleaned);
	# });
	# clip_text = filtered_lines.join('\n') + '\n';


	def remove_markdown(content: str) -> str:
		content = re.sub(r'\*\*(.*?)\*\*', r'\1', content)  # Bold: **text**
		content = re.sub(r'__(.*?)__', r'\1', content)      # Bold: __text__
		content = re.sub(r'\*(.*?)\*', r'\1', content)      # Italics: *text*
		content = re.sub(r'_(.*?)_', r'\1', content)        # Italics: _text_
		content = re.sub(r'`(.*?)`', r'\1', content)        # Inline code: `text`
		content = re.sub(r'#+\s(.*)', r'\1', content)       # Headings: # text
		content = re.sub(r'!\[.*?\]\(.*?\)', '', content)   # Images: ![alt text](url)
		content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)  # Links: [text](url)
		content = re.sub(r'^\s*[-\*]\s+', '', content, flags=re.MULTILINE)  # Bulleted lists: - text or * text
		return content

	# *************************************************
	# handle local llm responses, Ollama and LM Studio:
	# *************************************************

	# async for chunk in run_streamer(user_session.provider, user_session.chat_history):
	#   await ui.context.client.connected() # necessary?
	#   user_session.response_message.clear() # cleared for each chunk = why?
	#   with user_session.response_message:
	#       user_session.chunks += "" if chunk is None else chunk
	#       ui.html(f"<pre style='white-space: pre-wrap;'><br>AI:\n{user_session.chunks}</pre>")
	#   # show elapsed time, clock time, calendar date, and update stamp in ui.chat_message:
	#   end_time = time.time()
	#   elapsed_time = end_time - user_session.start_time
	#   minutes, seconds = divmod(elapsed_time, 60)
	#   end_time_date = f"{int(minutes)}:{seconds:.2f} elapsed at " + datetime.now().strftime("%I:%M:%S %p") + " on " + datetime.now().strftime("%A, %b %d, %Y")
	#   user_session.response_message.props(f'stamp="{end_time_date}"')
	#   user_session.response_message.update()
	#   try:
	#       await ui.context.client.connected() # necessary?
	#       await ui.run_javascript('scrollable.scrollTo(0, scrollable.scrollHeight)')
	#   except Exception as e:
	#       user_session.thinking_label.set_visibility(False)
	#       user_session.send_button.set_enabled(True)


	async def update_response_message_container(content: str):
		# show elapsed time, clock time, calendar date, and update stamp in ui.chat_message:
		end_time = time.time()
		elapsed_time = end_time - user_session.start_time
		minutes, seconds = divmod(elapsed_time, 60)
		end_time_date = f"{int(minutes)}:{seconds:.2f} elapsed at " + datetime.now().strftime("%I:%M:%S %p") + " on " + datetime.now().strftime("%A, %b %d, %Y")
		if content.startswith('<<FIN_LOCAL>>'):
			try:
				# user_session.response_message.props(f'stamp="{end_time_date}"')
				# user_session.response_message.update()
				# await user_session.ui_page.run_javascript('scrollable.scrollTo(0, scrollable.scrollHeight)')
				user_session.thinking_label.set_visibility(False)
				user_session.send_button.set_enabled(True)
				user_session.abort_stream.set_visibility(False)
			except Exception as e:
				print(e)
				pass
			return
		try:
			clean_content = remove_markdown(content)
			escaped_content = html.escape(clean_content)
			with user_session.message_container:
				await ui.context.client.connected() # necessary?
				user_session.response_message.clear() # cleared for each chunk = why?
				with user_session.response_message:
					user_session.chunks += "" if escaped_content is None else escaped_content
					ui.html(f"<pre style='white-space: pre-wrap;'><br>AI:\n{user_session.chunks}</pre>")
				user_session.response_message.props(f'stamp="{end_time_date}"')
				user_session.response_message.update()
				await ui.run_javascript('scrollable.scrollTo(0, scrollable.scrollHeight)')
		except Exception as e:
			print(e)
			user_session.thinking_label.set_visibility(False)
			user_session.send_button.set_enabled(True)
			user_session.abort_stream.set_visibility(False)
			pass


	# unique websocket name per user, "don't cross those streams!"", 
	# and this is only for users that are running: Ollama or LM Studio:
	@app.websocket(user_settings.websocket_name)
	async def websocket_endpoint(websocket: WebSocket):
		try:
			await websocket.accept()
			while True:
				data = await websocket.receive_text()
				parsed_data = json.loads(data)
				message = parsed_data.get('message') or parsed_data.get('messages', [{}])[0].get('content')
				if message:
					await update_response_message_container(message)
		except WebSocketDisconnect as e:
			print(f"websocket_endpoint: javascript streamer disconnected with code: {e.code}, reason: {e.reason}")
			print(e)
			pass
		except Exception as e:
			print(e)
			pass
		finally:
			try:
				# usually this is already closed, but just in case:
				await websocket.close()
			except Exception as e:
				pass

	# *************************************************
	# handle local llm responses, Ollama and LM Studio.
	# *************************************************


	def set_abort(value):
		user_session.abort = value

	def convert_to_int(s: str, default: int) -> int:
		try:
			return int(s)
		except ValueError:
			return default
		except Exception:
			return default

	# ***************************************************
	# ALL backend API stuff: model listers and streamers:
	# ***************************************************

	# **********************
	# provider model listers:
	# **********************

	async def app_models():
		user_settings.provider_models["Keys2Text"] = [
			"Insert a Note",
			"Vitals",
			"ReadMe",
		]
		return len(user_settings.provider_models["Keys2Text"])

	async def duckduckgo_models():
		user_settings.provider_models["DuckDuckGo"] = [
			"gpt-4o-mini",
			"claude-3-haiku-20240307",
			"meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
			"mistralai/Mixtral-8x7B-Instruct-v0.1",
		]
		return len(user_settings.provider_models["DuckDuckGo"])

	async def anthropic_models():
		pm = "Anthropic"
		provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
		if provider_api_key is None or provider_api_key.strip() == "":
			user_session.providers.remove(pm) if pm in user_session.providers else None
			return 0
		# # hardcoded coz they don't provide a 'list models' endpoint <= WHY?
		# user_settings.provider_models["Anthropic"] = [
		# 	"claude-3-5-haiku-20241022",
		# 	"claude-3-5-sonnet-20241022",
		# 	"claude-3-5-sonnet-20240620",
		# 	"claude-3-haiku-20240307",
		# 	"claude-3-opus-20240229",
		# 	"claude-3-sonnet-20240229",
		# ]
		# return len(user_settings.provider_models["Anthropic"])
		# Dec 2024: they added a list models endpoint:
		client = anthropic.Anthropic(
			api_key=provider_api_key,
			max_retries=0,
		)
		models = client.models.list(limit=1000) # default=20
		model_ids = [model.id for model in models.data]
		sorted_models = sorted(model_ids)
		user_settings.provider_models[pm] = sorted_models
		return len(user_settings.provider_models[pm])

	async def groq_models():
		pm = "Groq"
		try:
			provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
			if provider_api_key is None or provider_api_key.strip() == "":
				user_session.providers.remove(pm) if pm in user_session.providers else None
				return 0
			provider_timeout = user_settings.get_provider_setting(pm, 'timeout')
			client = Groq(
				api_key=provider_api_key,
				timeout=provider_timeout,
				max_retries=0, 
			)
			models = client.models.list()
			model_ids = [model.id for model in models.data if 'whisper' not in model.id.lower()]
			sorted_models = sorted(model_ids)
			user_settings.provider_models[pm] = sorted_models
			return len(user_settings.provider_models[pm])
		except Exception as e:
			user_session.providers.remove(pm) if pm in user_session.providers else None
			return 0

	async def google_models():
		pm = "Google"
		try:
			provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
			if provider_api_key is None or provider_api_key.strip() == "":
				user_session.providers.remove(pm) if pm in user_settings.providers else None
				return 0 # ignore when no api key
			genai.configure(api_key=provider_api_key)
			chat_models = []
			provider_timeout = user_settings.get_provider_setting(pm, 'timeout')
			for model in genai.list_models(request_options={"timeout": provider_timeout}):
				chat_models.append(model.name)
			sorted_models = sorted(chat_models)
			user_settings.provider_models[pm] = sorted_models
			return len(user_settings.provider_models[pm])
		except Exception as e:
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			return 0

	async def openai_models():
		pm = "OpenAI"
		try:
			provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
			if provider_api_key is None or provider_api_key.strip() == "":
				user_session.providers.remove(pm) if pm in user_settings.providers else None
				return 0
			provider_timeout = user_settings.get_provider_setting(pm, 'timeout')
			client = OpenAI(
				api_key=provider_api_key,
				timeout=provider_timeout,
				max_retries=0, 
			)
			models = client.models.list()
			model_ids = [model.id for model in models.data]
			sorted_models = sorted(model_ids)
			user_settings.provider_models[pm] = sorted_models
			# chat_models = [model for model in models.data if model.id.startswith("gpt")]
			# sorted_chat_models = sorted(chat_models, key=lambda x: x.created, reverse=True)
			# openai_model_ids = [model.id for model in sorted_chat_models if "gpt" in model.id]
			# user_settings.provider_models[pm] = openai_model_ids
			return len(user_settings.provider_models[pm])
		except Exception as e:
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			return 0

	async def openrouter_models():
		pm = "OpenRouter"
		try:
			provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
			if provider_api_key is None or provider_api_key.strip() == "":
				user_session.providers.remove(pm) if pm in user_settings.providers else None
				return 0
			provider_base_url = user_settings.get_provider_setting(pm, 'base_url')
			if provider_base_url is None or provider_base_url.strip() == "":
				user_session.providers.remove(pm) if pm in user_settings.providers else None
				return 0
			provider_timeout = user_settings.get_provider_setting(pm, 'timeout')
			client = OpenAI(
				base_url=provider_base_url,
				api_key=provider_api_key,
				timeout=provider_timeout,
				max_retries=0,
			)
			models = client.models.list()
			model_ids = [model.id for model in models.data]
			sorted_models = sorted(model_ids)
			user_settings.provider_models[pm] = sorted_models
			return len(user_settings.provider_models[pm])
		except Exception as e:
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			return 0

	# **********************************
	# model streamers for each provider:
	# **********************************

	async def OpenRouterResponseStreamer(prompt):
		if user_session.model is None: yield ""; return # sometimes model list is empty
		pm = "OpenRouter"
		provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
		if provider_api_key is None or provider_api_key.strip() == "":
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			yield ""; return
		provider_base_url = user_settings.get_provider_setting(pm, 'base_url')
		if provider_base_url is None or provider_base_url.strip() == "":
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			yield ""; return
		provider_timeout = user_settings.get_provider_setting(pm, 'timeout')
		try:
			client = OpenAI(
			  base_url=provider_base_url,
			  api_key=provider_api_key, 
			  timeout=provider_timeout,
			  max_retries=0,
			)
			params = {
				"model": user_session.model,
				"messages": [{"role": "user", "content": prompt}],
				"stream": True,
			}
			if user_session.ui_knob_temp.value is not None: params["temperature"] = user_session.ui_knob_temp.value
			stream = client.chat.completions.create(**params)
			for chunk in stream:
				if user_session.abort:
					set_abort(False)
					yield f"\n... response stopped by button click."
					stream.close()  # properly close the generator
					break  # exit the generator cleanly
				content = chunk.choices[0].delta.content
				if isinstance(content, str):
					cleaned_content = content.replace("**", "") # no ugly Markdown in plain text
					yield cleaned_content
				else:
					yield ""  # handle None or any unexpected type by yielding an empty string
		except Exception as e:
			yield f"Error:\nOpenRouter's response for model: {user_settings.model}\n{e}"


	async def OpenAIResponseStreamer(prompt):
		if user_session.model is None: yield ""; return # sometimes model list is empty
		pm = "OpenAI"
		provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
		if provider_api_key is None or provider_api_key.strip() == "":
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			yield ""; return
		provider_timeout = user_settings.get_provider_setting(pm, 'timeout')
		try:
			client = OpenAI(api_key=provider_api_key)
			params = {
				"model": user_session.model,
				"messages": [{"role": "user", "content": prompt}],
				"stream": True,
			}
			if user_session.ui_knob_temp.value is not None: params["temperature"] = user_session.ui_knob_temp.value
			stream = client.chat.completions.create(**params)
			for chunk in stream:
				if user_session.abort:
					set_abort(False)
					yield f"\n... response stopped by button click."
					stream.close()  # properly close the generator
					break  # exit the generator cleanly
				content = chunk.choices[0].delta.content
				if isinstance(content, str):
					cleaned_content = content.replace("**", "") # no ugly Markdown in plain text
					yield cleaned_content
				else:
					yield ""  # handle None or any unexpected type by yielding an empty string
		except Exception as e:
			yield f"Error:\nOpen AI's response for model: {user_session.model}\n{e}"


	async def GoogleResponseStreamer(prompt):
		if user_session.model is None: yield ""; return # sometimes model list is empty
		pm = "Google"
		provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
		if provider_api_key is None or provider_api_key.strip() == "":
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			yield ""; return
		provider_timeout = user_settings.get_provider_setting(pm, 'timeout')
		try:
			genai.configure(api_key=provider_api_key)
			model = genai.GenerativeModel(model_name=user_session.model)
			# safety_settings = {
			#   'HARM_CATEGORY_HATE_SPEECH': HarmBlockThreshold.BLOCK_NONE,
			#   'HARM_CATEGORY_HARASSMENT': HarmBlockThreshold.BLOCK_NONE,
			#   'HARM_CATEGORY_SEXUALLY_EXPLICIT': HarmBlockThreshold.BLOCK_NONE,
			#   'HARM_CATEGORY_DANGEROUS': HarmBlockThreshold.BLOCK_NONE,
			# }
			# params = {
			#     "safety_settings": safety_settings,
			# }
			params = {}
			if user_session.ui_knob_temp.value is not None:
				params["generation_config"] = {
					"temperature": user_session.ui_knob_temp.value,
				}
			if provider_timeout is not None:
				params["request_options"] = {"timeout": provider_timeout}
			stream = model.generate_content(
				prompt,
				stream=True,
				**params
			)
			for chunk in stream:
				if user_session.abort:
					set_abort(False)
					yield f"\n... response stopped by button click."
					# not valid: stream.close()  # properly close the generator
					break  # exit the generator cleanly
				content = chunk.text
				if isinstance(content, str):
					cleaned_content = content.replace("**", "") # no ugly Markdown in plain text
					yield cleaned_content
				else:
					yield ""  # handle None or any unexpected type by yielding an empty string
		except Exception as e:
			yield f"Error:\nGoogle's response for model: {user_session.model}\n{e}"
		finally:
			# https://stackoverflow.com/questions/78780089/how-do-i-get-rid-of-the-annoying-terminal-warning-when-using-gemini-api
			# this may help with this app shutdown message:
			#   E0000 00:00:1734357622.139313 1081881 init.cc:229] grpc_wait_for_shutdown_with_timeout() timed out.
			# these have no effect: 
			#   suppress logging warnings
			#   os.environ["GRPC_VERBOSITY"] = "ERROR"
			#   os.environ["GLOG_minloglevel"] = "2"
			# nor as export's (printenv)
			# ... google is such a wingnut:
			try:
				await asyncio.sleep(0.1) # small grace period for connection cleanup
			except Exception:
				pass

	async def AnthropicResponseStreamer(prompt):
		if user_session.model is None: yield ""; return # sometimes model list is empty
		pm = "Anthropic"
		provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
		if provider_api_key is None or provider_api_key.strip() == "":
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			yield ""; return
		provider_timeout = user_settings.get_provider_setting(pm, 'timeout')
		try:
			client = anthropic.Anthropic(
				api_key=provider_api_key,
				timeout=provider_timeout,
				max_retries=0,
			)
			params = {
				"messages": [{"role": "user", "content": prompt}],
				"model": user_session.model,
				"max_tokens": user_settings.get_provider_setting('Anthropic', 'max_tokens'), # error if this is missing <= why?
				}
			if user_session.ui_knob_temp.value is not None: params["temperature"] = user_session.ui_knob_temp.value
			with client.messages.stream(**params) as stream:
				for content in stream.text_stream:
					if user_session.abort:
						set_abort(False)
						yield f"\n... response stopped by button click."
						stream.close()  # properly close the generator
						break  # exit the generator cleanly
					if isinstance(content, str):
						cleaned_content = content.replace("**", "") # no ugly Markdown in plain text
						yield cleaned_content
					else:
						yield "" # handle None or any unexpected type by yielding an empty string

		except Exception as e:
			print(e)
			yield f"Error:\nAnthropic's response for model: {user_session.model}\n{e}"


	async def GroqResponseStreamer(prompt):
		if user_session.model is None: yield ""; return # sometimes model list is empty
		pm = "Groq"
		provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
		if provider_api_key is None or provider_api_key.strip() == "":
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			yield ""; return
		provider_timeout = user_settings.get_provider_setting(pm, 'timeout')
		try:
			client = AsyncGroq(
				api_key=user_settings.get_provider_setting(pm, 'api_key'), 
				timeout=provider_timeout,
				max_retries=0, 
			)
			params = {
				"model": user_session.model,
				"messages": [{"role": "user", "content": prompt}],
				"stream": True,
				"stop": None,
			}
			if user_session.ui_knob_temp.value is not None: params["temperature"] = user_session.ui_knob_temp.value
			try:
				stream = await client.chat.completions.create(**params)
				async for chunk in stream:
					if user_session.abort:
						set_abort(False)
						yield f"\n... response stopped by button click."
						await stream.close()  # properly close the generator
						break  # exit the generator cleanly
					content = chunk.choices[0].delta.content
					if isinstance(content, str):
						cleaned_content = content.replace("**", "") # no ugly Markdown in plain text
						yield cleaned_content
					else:
						yield " "  # handle None or any unexpected type by yielding an empty string
			except GeneratorExit:
				await stream.close()  # ensure the generator is closed even on GeneratorExit
				return  # exit gracefully after handling GeneratorExit
		except Exception as e:
			yield f"Error:\nGroq's response for model: {user_session.model}\n{e}"


	async def LMStudioResponseStreamer(prompt):
		if user_session.model is None: yield ""; return # sometimes model list is empty
		pm = "LMStudio"
		provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
		if provider_api_key is None or provider_api_key.strip() == "":
			provider_api_key = 'lmstudio' # no api_key is required, so force it
			# user_session.providers.remove(pm) if pm in user_settings.providers else None
			# yield ""; return
		provider_base_url = user_settings.get_provider_setting(pm, 'base_url')
		if provider_base_url is None or provider_base_url.strip() == "":
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			yield ""; return
		# provider_timeout = user_settings.get_provider_setting(pm, 'timeout') # unused coz js local
		provider_base_url = provider_base_url.removesuffix("/")
		url = f"{provider_base_url}{user_session.openai_compat_chat_endpoint}"
		try:
			# the localStreamChat js returns instantly, see: 
			#   process_chunk_into_text_for_ui_chat_message()
			#   update_response_message_container()
			# ... for details about chunk processing via js + endpoint + nicegui:
			js_code = f'localStreamChat("{user_settings.websocket_name}", "{url}", "{provider_api_key}", "{user_session.model}", {escape_js_string(prompt)})'
			ui.run_javascript(js_code)
		except Exception as e:
			print(e)


	async def OllamaResponseStreamer(prompt):
		# start ollama like this:
		# OLLAMA_ORIGINS="http://127.0.0.1,https://app.novelcrafter.com" ollama serve
		if user_session.model is None: yield ""; return # sometimes model list is empty
		pm = "Ollama"
		provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
		if provider_api_key is None or provider_api_key.strip() == "":
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			yield ""; return
		provider_base_url = user_settings.get_provider_setting(pm, 'base_url')
		if provider_base_url is None or provider_base_url.strip() == "":
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			yield ""; return
		# provider_timeout = user_settings.get_provider_setting(pm, 'timeout') # unused coz js local
		provider_base_url = provider_base_url.removesuffix("/")
		url = f"{provider_base_url}{user_session.openai_compat_chat_endpoint}"
		try:
			js_code = f'localStreamChat("{user_settings.websocket_name}", "{url}", "{provider_api_key}", "{user_session.model}", {escape_js_string(prompt)})'
			ui.run_javascript(js_code)
		except Exception as e:
			print(e)


	async def DuckDuckGoResponseStreamer(prompt):
		if user_session.model is None: yield ""; return # sometimes model list is empty
		pm = "DuckDuckGo"
		provider_base_url = user_settings.get_provider_setting(pm, 'base_url')
		if provider_base_url is None or provider_base_url.strip() == "":
			user_session.providers.remove(pm) if pm in user_settings.providers else None
			yield ""; return
		provider_timeout = user_settings.get_provider_setting(pm, 'timeout')
		messages = []
		messages.append({"content": prompt, "role": "user"})
		try:
			no_response = True # assume worst with DDG AI coz of a daily limit on usage
			atimeout = httpx.Timeout(provider_timeout, connect=10.0)
			async with httpx.AsyncClient(timeout=atimeout) as client:
				try:
					# print(f"vqd={user_session.duckduckgo_vqd}")
					headers = {
						"Content-Type": "application/json",
						"x-vqd-4": user_session.duckduckgo_vqd,
						"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
					}
					payload = {
						"model": user_session.model,
						"messages": messages
					}

					# a way to see headers in a post request:
					# request = client.build_request("POST", provider_base_url, headers=headers, json=payload)
					# print('headers:')
					# print(request.headers)

					response = await client.post(provider_base_url, headers=headers, json=payload)
					if response.status_code == 200:
						# if 'Transfer-Encoding' in response.headers and response.headers['Transfer-Encoding'] == 'chunked':
						#   print("Response is being streamed (chunked).")
						async for line in response.aiter_lines():
							if line.strip():
								no_response = False # DDG AI said something
								line = line.strip()
								if line == "data: [DONE]":
									break
								if line.startswith("data: "):
									try:
										data = json.loads(line[6:])
										message = data.get("message", "")
										if message:
											yield message
									except json.JSONDecodeError:
										continue
								else:
									yield ""  # handle None or any unexpected type by yielding an empty string
					if no_response:
					    yield f"DuckDuckGo AI is not available at this time!\n"
					    yield f"\n"
					    yield f"***********************************************************************************************************************************************\n"
					    yield f"* DuckDuckGo AI is provided as a demonstration feature for those new to AI chat models.                                                       *\n"
					    yield f"*                                                                                                                                             *\n"
					    yield f"* Please note that DuckDuckGo AI has a daily usage limit shared among all Keys2Text users.                                                    *\n"
					    yield f"*                                                                                                                                             *\n"
					    yield f"* Due to these limitations, the AI may not always respond to your prompts if the daily limit has been reached.                                *\n"
					    yield f"*                                                                                                                                             *\n"
					    yield f"* Consider signing up with an AI provider that offers an API key, such as Groq or OpenRouter, who also offer free AI models.                  *\n"
					    yield f"*                                                                                                                                             *\n"
					    yield f"* While using DuckDuckGo AI, you can experience basic AI chat capabilities and learn how to interact with AI models, but only when available. *\n"
					    yield f"***********************************************************************************************************************************************\n"
					    yield f"\n"
				except Exception as e:
					yield f"Error:\nDuckDuckGo's response for model: {user_session.model}\n{e}"
		except Exception as e:
			yield f"Error:\nDuckDuckGo's response for model: {user_session.model}\n{e}"

	# **********************************
	# end of backend provider API stuff.
	# **********************************

	async def Keys2TextResponseStreamer(prompt):
		if user_session.model is None: yield ""; return # sometimes model list is empty
		if user_session.model == "Vitals":
			try:
				uvv = version('uvicorn')
			except PackageNotFoundError:
				uvv = 'unknown'
			try:
				fav = version('fastapi')
			except PackageNotFoundError:
				fav = 'unknown'
			user_session.total_models = sum(len(models) for models in user_settings.provider_models.values())
			# ignore the chat app's pretend ai/llm stuff:
			total_ai_providers = len(user_session.providers) - 1
			ignored = len(user_settings.provider_models["Keys2Text"])
			total_ai_models = user_session.total_models - ignored
			yield f"Platform: {platform.system()}\n"
			# yield f"Server listening at:\n"
			# for url in app.urls:
			#   yield f"\t{url}\n"
			yield f"Session ID: {user_session.session_id.get('id')}\n"
			yield f"\nKeys2Text chat personal server info:\n"
			yield f"\tYour connection IP: {ui.context.client.ip}\n"
			yield f"\n*** AI Providers and their LLM Models ***\n"
			yield f"In total there are {total_ai_models} models available from {total_ai_providers} providers.\n"
			for index, provider in enumerate(user_session.providers, start=0):
				if provider == "Keys2Text":
					continue
				models = user_settings.provider_models.get(provider, [])
				model_count = len(models)
				yield f"\n(#{index}). {provider}  models: {model_count} ...\n"
				for m, model in enumerate(models, start=1):
					yield f"{m}. {model}\n"
			pvi = sys.version_info
			python_version = f"{pvi.major}.{pvi.minor}.{pvi.micro}"
			nicegui_version = nv
			anthropic_version = av
			genai_version = ggv
			groq_version = gv
			openai_version = oav
			yield f"\n\n--- Software Versions ---\n"
			yield f"Keys2Text: {user_settings.app_version}\n"
			yield f"Python: {python_version}\n"
			yield f"NiceGUI: {nicegui_version}\n"
			yield f"FastAPI: {fav}\n"
			yield f"Uvicorn: {uvv}\n"
			yield f"\n--- AI Provider's SDK versions ---\n"
			yield f"1. Anthropic: {anthropic_version}\n"
			yield f"2. Google Generativeai: {genai_version}\n"
			yield f"3. Groq: {groq_version}\n"
			yield f"4. OpenAI: {openai_version}\n"
			yield f"5. DuckDuckGo AI: ?\n"
			# yield "\nSaved chat histories for this session:\n"
			# if not user_settings.saved_chat_histories:
			#   yield "nothing\n"
			# else:
			#   for chat in user_settings.saved_chat_histories:
			#       yield f"{chat}\n"
		else:
			import random
			import string
			yield f"The following is a <i>all-in-one</i> README, wish list, and stream tester.\n\n"
			yield f"I wish all of the AI chatters in the universe:\n\n"
			yield f"- maintained a simple plain text chat history file, for both human and AI\n"
			yield f"- denoted the ME: and the AI: in their chat history (ok, some of them do this already)\n"
			yield f"- denoted which Provider and Model are being used, so we know who we chatted with\n"
			yield f"- timestamped the chat with a human readable date and time\n"
			yield f"- would allow us to 'Insert a Note' along with a timestamp into the chat history\n"
			yield f"- were easy and fast to scroll chat history: ⬇ (to the bottom) and ⬆ (to the top)\n"
			yield f"- could CLEAR to forget and start a new chat (ok, most do this already)\n"
			yield f"- could COPY an entire chat to the clipboard\n"
			yield f"- could SAVE an entire chat as a plain text file ... none of them; enough already with the JSON, Markdown, RTF, and Word\n"
			yield f"- would allow us to use our cursor/pointer to select text in this box to copy/paste just what you need  (ok, most of them do this already)\n"
			yield f"- would remove those '**' (Markdown), this app removes most of the Markdown\n"
			yield f"- could continue the same chat across several AI models\n"
			yield f"- used NiceGUI and worked in many web browsers\n"
			yield f"\nOk, now, the all 🌊 seems fine, let's test a stream of randomness:\n"
			for i in range(10):
				await asyncio.sleep(0.2)
				random_word = "".join(
					random.choices(string.ascii_lowercase, k=random.randint(1, 13))
				)
				yield f" A{random_word}E-{i+1} "  # either front/end space works
			yield f" \n"
			yield f"\nYou are 'go at throttle up' 🚀\n"
			yield f"Enjoy! ☮️\n"
			yield f"p.s. click on CLEAR above to get rid of this, I await your return! 🙉\n"

	# map the PROVIDERS to their corresponding streamer, so
	# the 'async def' for each must be defined before here.
	STREAMER_MAP = {
		"Keys2Text": Keys2TextResponseStreamer,
		"Anthropic": AnthropicResponseStreamer,
		"Google": GoogleResponseStreamer,
		"Groq": GroqResponseStreamer,
		"OpenAI": OpenAIResponseStreamer,
		"OpenRouter": OpenRouterResponseStreamer,
		"LMStudio": LMStudioResponseStreamer,
		"Ollama": OllamaResponseStreamer,
		"DuckDuckGo": DuckDuckGoResponseStreamer,
	}

	async def run_streamer(provider, prompt):
		streamer_function = STREAMER_MAP.get(provider)
		if streamer_function is None:
			yield f"No streamer found for provider: {provider}"
			return
		async for chunk in streamer_function(prompt):
			if user_session.abort:
				set_abort(False)
				await asyncio.sleep(1.0)
				return  # exit the generator cleanly?
			yield chunk

	def append_splash_text(model_log, providers_models, new_text: str):
		providers_models.append(new_text)
		model_log.set_content('<br>'.join(providers_models))

	async def make_a_splash():
		with ui.dialog() as splash_popup:
			splash_popup.props("persistent")
			splash_popup.classes("blur(4px)")
			with splash_popup, ui.card().classes("w-96"):
				ui.image("https://www.slipthetrap.com/images/Aidetour_bw.png").classes("w-64 h-64 mx-auto")
				ui.label("Welcome to Keys2Text!").classes("text-2xl font-bold text-center mt-2")
				for url in app.urls:
					ui.link(url, target=url)
				with ui.row().classes("justify-center mt-2"):
					ui.spinner('grid', size='sm')
					ui.label("Please standby . . .").classes("text-red text-sm text-center mt-2 ml-2")
				model_log = ui.html().classes("text-sm mt-2").style('white-space: pre-wrap')
				providers_models = []
		splash_popup.open()
		return splash_popup, model_log, providers_models


	async def fetch_vqd():
		url = "https://duckduckgo.com/duckchat/v1/status"
		headers = {
			"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
			"x-vqd-accept": "1"
		}
		async with httpx.AsyncClient() as client:
			response = await client.get(url, headers=headers)
			if response.status_code == 200:
				return response.headers.get("x-vqd-4")
			else:
				raise Exception(f"fetch_vqd: Failed to initialize chat: {response.status_code} {response.text}")

	# **********************
	# start ui via nicgui:
	# **********************

	user_settings.current_primary_color = user_settings.current_primary_color if user_settings.current_primary_color is not None else '#4CAF50' # green
	ui.colors(primary=str(user_settings.current_primary_color))

	darkness = ui.dark_mode()
	darkness_value = user_settings.darkness if user_settings.darkness is not None else True
	darkness.set_value(darkness_value)

	user_session.splash_dialog, model_log, providers_models = await make_a_splash()
	model_count = await app_models()

	user_session.provider = "Keys2Text"
	user_session.model = user_settings.provider_models.get(user_session.provider, ['Keys2Text'])[0]

	# let's try to give users access to the free LLM models on DuckDuckGo AI, 
	# we 'try' coz there's no official DuckDuckGo AI API and this may 
	# stop working ... but it's nice for app demos:
	try:
		user_session.duckduckgo_vqd = await fetch_vqd()
		# print(f"vqd={user_session.duckduckgo_vqd}")
	except Exception as e:
		print(e)

	def update_model_choices():
		selected_provider = user_session.ui_select_provider.value
		available_models = user_settings.provider_models.get(selected_provider, [])
		user_session.ui_select_model.options = available_models
		user_session.ui_select_model.value = available_models[0] if available_models else ''
		user_session.ui_select_model.update()

	def clear_temp(e):
		user_session.ui_knob_temp.value = None
		user_session.ui_knob_temp.update()  # refresh the UI to reflect changes

	async def windowInnerHeight():
		window_innerHeight = await ui.run_javascript(f"window.innerHeight")
		return window_innerHeight

	# async def windowInnerWidth():
	#   window_innerWidth = await ui.run_javascript(f"window.innerWidth")
	#   return window_innerWidth

	async def copy_chat():
		text = await ui.run_javascript(f"getElement({user_session.message_container.id}).innerText")
		# this also works and may make more sense than using: user_settings.message_container.id:
		# text = await ui.run_javascript(f"return document.getElementById('scrollable').innerText;")

		# let's use a single generator expression to iterate through the lines of text, 
		# to filter by removing Markdown: "**", "##", "###", stripping whitespace, 
		# and ignoring lines with just "content_paste" (i.e. copy button)
		# ... which should be more efficient for large chat texts 
		# because it avoids unnecessary list creation and 
		# performs both filtering operations in a single pass:
		filtered_lines = (
			re.sub(r"\*\*|##|###", "", line).strip() 
			for line in text.splitlines() 
			if re.sub(r"\*\*|##|###", "", line).strip() != "content_paste"
			if re.sub(r"\*\*|##|###", "", line).strip() != "edit"
		)
		text_without_markdown_and_content_paste = "\n".join(filtered_lines)
		escaped_text = text_without_markdown_and_content_paste
		if escaped_text.startswith('"') and escaped_text.endswith('"'):
			safe_text = escaped_text[1:-1]
		else:
			safe_text = escaped_text
		safe_text_js = json.dumps(safe_text)
		return safe_text_js


	async def clear_chat():
		user_session.message_container.clear()
		user_session.chat_history = ""
		# get a list of all objects tracked by the garbage collector
		# all_objects = gc.get_objects()
		# print(len(all_objects))
		# gc.collect()
		# all_objects = gc.get_objects()
		# print(len(all_objects))


	async def save_chat(text) -> None:
		text = await ui.run_javascript(f"getElement({user_session.message_container.id}).innerText")
		# generate the filename with epoch timestamp
		timestamp = int(time.time())
		filename = f"{timestamp}_Keys2Text_chat_history.txt"
		try:
			# filter out markdown and specific unwanted content
			filtered_lines = (
				re.sub(r"\*\*|##|###", "", line).strip()
				for line in text.splitlines()
				if re.sub(r"\*\*|##|###", "", line).strip() != "content_paste"
				if re.sub(r"\*\*|##|###", "", line).strip() != "edit"
			)
			text_without_markdown_and_content_paste = "\n".join(filtered_lines)
			if len(text_without_markdown_and_content_paste) > 0:
				# when running app online, we download:
				ui.download(text_without_markdown_and_content_paste.encode('utf-8'), filename)

				# when running app locally, we may save to file:
				# filepath = os.path.join(Keys2Text_APP_PATH, filename)
				# with open(filepath, "w", encoding='utf-8') as file:
				#   file.write(text_without_markdown_and_content_paste)
				# user_settings.saved_chat_histories.append(filepath)

				ui.notify(f"Chat history will be downloaded as: {filename}", position="top")
			else:
				ui.notify(f"There is no chat history to download ?", position="top")
		except Exception as e:
			ui.notify(f"Error downloading chat history file: {filename}:\n{e}", position="top")

	# def clean_text_for_ai(text):
	#     # remove non-printable and control characters but keep spaces, tabs, and newlines
	#     cleaned_text = ''.join(
	#         char for char in text 
	#         if char.isprintable() or char in ('\n', '\r', '\t')
	#     )
	#     return cleaned_text

	def escape_js_string(text):
		"""escape a Python string for safe inclusion in JavaScript code."""
		return json.dumps(text)  # automatically escapes quotes, backslashes, newlines, etc.


	async def send_prompt_to_ai() -> None:
		prompt_sent = bool(user_prompt.value and user_prompt.value.strip())
		user_session.provider = user_session.ui_select_provider.value
		user_session.model = user_session.ui_select_model.value
		if user_session.provider == 'Keys2Text':
			pass
		elif not prompt_sent:
			ui.notify("Prompt is empty, please type something.", position="top", timeout=2000)
			return
		if user_session.provider == 'Keys2Text':
			pass
		else:
			user_session.chat_history += user_prompt.value + " \n"
		question = user_prompt.value
		user_prompt.value = ''

		# disable Send button, start Thinking, show Abort stream:
		user_session.send_button.set_enabled(False)
		user_session.thinking_label.set_visibility(True)
		user_session.abort_stream.set_visibility(True)

		# track the elapsed time from sent message until end of response message:
		user_session.start_time = time.time()

		user_session.response_message = None
		with user_session.message_container:
			timestamp = datetime.now().strftime("%I:%M:%S %p") + " on " + datetime.now().strftime("%A, %b %d, %Y")
			me_message = ui.chat_message(sent=True, stamp=timestamp)
			me_message.clear()
			with me_message:
				if user_session.provider == 'Keys2Text' and user_session.model == 'Insert a Note':
					ui.html(f"<pre style='white-space: pre-wrap;'>\nKeys2Text:   [{user_session.model}]:\n{question}</pre>")
				elif user_session.provider == 'Keys2Text':
					pass
				else:
					ui.html(f"<pre style='white-space: pre-wrap;'>ME:   {user_session.provider} - {user_session.model} - temp: {user_session.ui_knob_temp.value}\n{question}</pre>")

			user_session.response_message = ui.chat_message(sent=False, stamp=timestamp)

		# accumulate/concatenate AI's response as chunks:
		user_session.chunks = ""

		try:
			await ui.context.client.connected() # necessary?
			await ui.run_javascript('scrollable.scrollTo(0, scrollable.scrollHeight)')
		except Exception as e:
			pass # no biggie, if can't scroll then user can do it manually

		if user_session.provider == 'Keys2Text' and user_session.model == 'Insert a Note':
			# just 'Insert a Note' in as 'ME:' and no need to stream it
			await ui.run_javascript('scrollable.scrollTo(0, scrollable.scrollHeight)')
			user_session.thinking_label.set_visibility(False)
			user_session.send_button.set_enabled(True)
			user_session.abort_stream.set_visibility(False)
		else:
			async for chunk in run_streamer(user_session.provider, user_session.chat_history):
				if user_session.abort:
					set_abort(False)
					break
				await ui.context.client.connected() # necessary?
				user_session.response_message.clear() # cleared for each chunk = why?
				with user_session.response_message:
					user_session.chunks += "" if chunk is None else chunk
					if user_session.provider == 'Keys2Text':
						ui.html(f"<pre style='white-space: pre-wrap;'><br>Keys2Text:   [{user_session.model}]  {timestamp}:\n{user_session.chunks}</pre>")
					else:
						ui.html(f"<pre style='white-space: pre-wrap;'><br>AI:\n{user_session.chunks}</pre>")
				
				# show elapsed time, clock time, calendar date, and update stamp in ui.chat_message:
				end_time = time.time()
				elapsed_time = end_time - user_session.start_time
				minutes, seconds = divmod(elapsed_time, 60)
				end_time_date = f"{int(minutes)}:{seconds:.2f} elapsed at " + datetime.now().strftime("%I:%M:%S %p") + " on " + datetime.now().strftime("%A, %b %d, %Y")
				if user_session.provider == 'DuckDuckGo':
					end_time_date += f" - DuckDuckGo models are not streamed, so they have slower responses."
				user_session.response_message.props(f'stamp="{end_time_date}"')
				user_session.response_message.update()
				try:
					await ui.context.client.connected() # necessary?
					await ui.run_javascript('scrollable.scrollTo(0, scrollable.scrollHeight)')
				except Exception as e:
					user_session.thinking_label.set_visibility(False)
					user_session.send_button.set_enabled(True)

			user_session.thinking_label.set_visibility(False)
			user_session.send_button.set_enabled(True)
			user_session.abort_stream.set_visibility(False)

		user_session.chunks = ""
		# ************************
		# *** stream has ended ***
		# ************************

		async def copy_prompt_ME_back_to_prompt(prompt):
			try:
				prompt_text = await ui.run_javascript(f"return document.getElementById('c{prompt.id}').innerText;")
				lines = prompt_text.splitlines()
				if len(lines) > 2:
					prompt_text = '\n'.join(lines[1:-1])
				else:
					prompt_text = '\n'.join(lines)
				user_prompt.value = prompt_text
				user_prompt.update()
				# annoying = ui.notify(f"The prompt inside ME: message was copied back to Prompt, so now you can edit and re-Send.", position="top", timeout=2000)
			except Exception as e:
				ui.notify(f"Unable to copy ME: message back to Prompt.  Error: {e}", position="top")

		# setup/handle copying a ME: + AI: chat pair to clipboard 
		# via nicegui button and javascript copyToClipboard in: 
		#   ui.add_body_html('''<script>... :
		try:
			with user_session.message_container:
				# why is the above 'with' needed? 
				#   to access user_session.response_message properly 
				#   in order to get the text inside of 2 div's (me/ai),
				#   i.e. the 'div id=cNUM' will be found.

				with user_session.response_message:
					chat_ai_response = user_session.response_message

				async def show_checkmark() -> None:
					me_ai_copy_button.props('icon=check color=green')
					await asyncio.sleep(2.0)
					me_ai_copy_button.props('icon=content_paste color=primary')

				me_ai_copy_button = ui.button(icon='content_copy', on_click=show_checkmark) \
					.on('click', js_handler=f'() => copyToClipboard("{me_message.id}", "{chat_ai_response.id}")') \
					.tooltip("copy this section (ME: + AI:) to the clipboard") \
					.props('icon=content_copy round flat') \
					.style("padding: 1px 1px; font-size: 9px;")

				if not (user_session.provider == 'Keys2Text' and user_session.model in ["Vitals", "ReadMe"]):
					ui.button(
						icon='edit',
						on_click=lambda: copy_prompt_ME_back_to_prompt(me_message)
					) \
					.tooltip("reuse this prompt for editing") \
					.props('icon=edit round flat') \
					.style("padding: 1px 1px; font-size: 9px;")

				ui.html(f"<pre style='white-space: pre-wrap;'><br></pre>")
			await ui.run_javascript('scrollable.scrollTo(0, scrollable.scrollHeight)')
		except Exception as e:
			ui.notify(f"Error: {e}", position="top")


	# *************************
	# page layout and elements:
	# *************************

	# custom css to remove the one pointy corner (that's used with avatar's) 
	# and ensure all corners are rounded:
	ui.add_head_html('''
	<style>
		/* remove the pointy pseudo-element */
		.q-message-text::before {
			content: none !important;
			display: none !important;
		}

		/* ensure all corners of the message bubble are rounded */
		.q-message-text {
			border-radius: 12px !important;
			background-color: transparent !important;
			border: 1px solid #B0B0B0 !important; /* add a neutral grey border */
		}

		.q-message-text-content {
			border-radius: 12px !important;
			background-color: transparent !important;
		}

		.dark .q-message-text-content {
			color: #cccccc !important; /* text color for dark mode */
		}
	</style>
	''')

	# this is not easy to understand, most of the issues are bad js syntax (not properly escaped)
	#   using ui.run_javascript is only possible after a client is connected
	# this doesn't always help, so we see "TimeoutError: JavaScript did not respond within 1.0 s":
	await ui.context.client.connected()

	wih = await windowInnerHeight() - 300 # leave some empty space at bottom of page
	# wiw = await windowInnerWidth() - 200 # not needed, width is responsive

	with ui.header().classes('bg-transparent text-gray-800 dark:text-gray-200 z-10 mt-0').style('margin-top: 0; padding-top: 0;'):

		with ui.row().classes("w-full no-wrap mb-0 mt-5 ml-0").style('min-width: 100%; margin-left: 0; justify-content: left;'):

			# allow case sensitivity in ui.select:
			ui.add_head_html(
				"<style> .prevent-uppercase { text-transform: none !important; } </style>"
			)
			with ui.avatar(color=None, square=False, rounded=True, size='lg').classes("mt-3"):
				image_url = user_settings.google_picture
				try:
					response = httpx.get(image_url, timeout=2)
					image_url = user_settings.google_picture if response.status_code == 200 else 'https://www.slipthetrap.com/images/Aidetour_bw.png'
				except Exception as e:
					image_url = 'https://www.slipthetrap.com/images/Aidetour_bw.png'
				ui.image(image_url)

				signin_time = user_settings.signin_time
				with ui.tooltip().classes('flex items-center justify-center w-auto h-auto p-5'):
					with ui.element().classes('flex flex-col items-center justify-center p-5'):
						ui.image('https://www.slipthetrap.com/images/Aidetour_bw.png').classes('w-56')
						ui.html(
						  "<p style='font-size:20px'><b>Keys2Text</p>"
						  f"<p style='font-size:12px'><b>version: {user_settings.app_version}</b></p>"
						  f"<p style='font-size:12px'><b>last Google sign in:<br>{datetime.utcfromtimestamp(signin_time).strftime('%Y-%m-%d %H:%M:%S')}</b></p><br>"
						  f"<p style='font-size:10px; text-align: left;'><i>The 8 providers offered:<br>"
						  f"{user_settings.eight_providers}</i></p>"
						).classes("text-center p-3").style(f"background-color: {user_settings.current_primary_color};")
						ui.separator().classes("mt-2 mb-2")
						with ui.row().classes('w-full items-center'):
							if user_settings.google_picture:
								with ui.avatar(rounded=True).style('background-color: transparent !important;'):
									ui.image(user_settings.google_picture)
							with ui.column().classes('ml-4 flex-grow'):
								# ui.label(user_settings.users_google_sub).classes('text-xl font-bold')
								ui.label(f"{user_settings.google_given_name} {user_settings.google_family_name}").classes('text-xl font-bold mb-0')
								with ui.row().classes('mt-0'):
									ui.label(user_settings.google_email).classes('text-sm')
									if user_settings.google_email_verified:
										ui.label("✓ verified").classes('text-green-600')
									else:
										ui.label("✗ not verified").classes('text-red-600')

			with ui.column().classes("flex-1 w-1/3 p-0 ml-0").style('transform: scale(0.85);'):
				user_session.ui_select_provider = (
					ui.select(
						user_session.providers,
						# label=f"? Providers:",
						label=f"Providers:",
						value=user_session.provider,
						on_change=lambda e: update_model_choices(),
					)
					.classes("prevent-uppercase w-40")
				)

			with ui.column().classes("flex-1 w-1/3 p-0").style('transform: scale(0.85);'):
				# user can type to search/select, like for the word 'free':
				user_session.ui_select_model = (
					ui.select(
						value=user_session.model,
						label="Models:",
						options=user_settings.provider_models[user_session.provider], 
						with_input=True,
					)
					.props("clearable")
					.props("spellcheck=false")
					.props("autocomplete=off")
					.props("autocorrect=off")
				)

			# user_settings.ui_select_provider.on_value_change(
			#   lambda e: user_settings.ui_select_model.props(
			#       f'label="{len(user_settings.provider_models.get(user_settings.provider))} Models:"' if user_settings.provider_models.get(user_settings.provider) else 'label="No Models Available"'
			#   ) if e.value != "Keys2Text" else user_settings.ui_select_model.props('label="Models:"')
			# )

			with ui.column().classes("flex-1 w-1/3 p-0 ml-3").style('transform: scale(0.85);'):
				# use gap-0 to make button/knob closer together:
				with ui.row().classes("mb-0 mt-0 ml-6 gap-0 items-center"):
					user_session.ui_button_temp = ui.button(
						icon='dew_point', #'device_thermostat',
						on_click=lambda e: clear_temp(None)
					) \
					.tooltip("clear/reset Temp") \
					.props('no-caps flat round')

					user_session.ui_knob_temp = ui.knob(
						None,
						min=None,
						max=2,
						step=0.1,
						show_value=True, 
						color=user_settings.current_primary_color,
						track_color='blue-grey-7',
						size='xl'
					) \
					.tooltip("Temperature")

		with ui.row().classes("w-full mb-0 mt-0 ml-0"):

			with ui.column().classes("flex-none p-0"):
				# SEND button and thinking label
				with ui.row().classes("items-center"):
					user_session.send_button = (
						ui.button(
							icon="send",
							on_click=lambda: send_prompt_to_ai(),
						)
						.props('outline')
						.classes("ml-0 mr-2 text-sm px-4 py-2 mt-5")
						.style(
							"box-shadow: 0 0 1rem 0 #546e7a; transition: transform 0.3s ease;"
						)
						# .props('icon=img:https://www.slipthetrap.com/images/Aidetour.png')
					)

					with user_session.send_button:
						with ui.tooltip('').props("flat fab"):
							ui.html("send Prompt")

					user_session.thinking_label = ui.spinner('grid', size='sm').classes("ml-1 mt-5") # , color='green')

			user_session.thinking_label.set_visibility(False)
			user_session.send_button.set_enabled(False)
			user_session.send_button.set_enabled(True)

			with ui.column().classes("flex-grow p-0"):
				user_prompt = (
					ui.textarea(label="Prompt:", placeholder=f"Enter your prompt here...")
					.classes("w-full")
					.props("clearable")
					.props("rows=2")
					.props("spellcheck=false")
					.props("autocomplete=off")
					.props("autocorrect=off")
					.props("tabindex=0")
				)

		with ui.row().classes("w-full mb-0.1 space-x-0"):
			# https://fonts.google.com/icons?icon.query=clip&icon.size=24&icon.color=%23e8eaed

			async def scroll_to_bottom():
				await ui.run_javascript('scrollable.scrollTo(0, scrollable.scrollHeight)')

			ui.button(icon='arrow_downward', on_click=scroll_to_bottom) \
			.tooltip("scroll to bottom") \
			.props('no-caps flat fab-mini')

			async def scroll_to_top():
				await ui.run_javascript('scrollable.scrollTo(0, 0)')

			ui.button(icon='arrow_upward', on_click=scroll_to_top) \
			.tooltip("scroll to top") \
			.props('no-caps flat fab-mini')

			async def copy_checkmark() -> None:
				copy_all_button.props('icon=check color=green')
				await asyncio.sleep(3.0)
				copy_all_button.props('icon=content_paste color=primary')

			safe_text_js_handler = """
			() => {
				let text = document.getElementById('scrollable').innerText;
				let filteredLines = Array.from(text.split('\\n'))
					.map(line => line.replace(/\\*\\*|##|###/g, "").trim())
					.filter(line => line !== "content_paste" && line !== "edit" && line !== "content_copy");
				let textWithoutMarkdownAndContentPaste = filteredLines.join('\\n');
				let escapedText = textWithoutMarkdownAndContentPaste;
				let safeText;
				if (escapedText.startsWith('"') && escapedText.endsWith('"')) {
					safeText = escapedText.slice(1, -1);
				} else {
					safeText = escapedText;
				}
				try {
					navigator.clipboard.writeText(safeText).then(() => {
						console.log('Chat history copied successfully');
					}).catch(err => {
						console.error('Failed to copy text:', err);
						alert('Clipboard operation failed. Please copy manually.');
					});
				} catch (err) {
					console.error('Clipboard API not supported:', err);
					alert('Clipboard operation failed. Please copy manually.');
				}
			}
			"""

			copy_all_button = ui.button(icon='content_copy', on_click=copy_checkmark) \
				.on('click', js_handler=safe_text_js_handler) \
				.tooltip("copy entire chat history to clipboard") \
				.props('no-caps flat fab-mini')

			ui.button(icon="delete_sweep", on_click=clear_chat) \
			.tooltip("clear chat history") \
			.props('no-caps flat fab-mini')

			ui.button(icon='save_as', on_click=save_chat) \
			.props('no-caps flat fab-mini') \
			.tooltip("download entire chat history as a text file")

			def update_tooltip(button, tooltip_text):
				button.props(f'tooltip="{tooltip_text}"')

			with ui.element():
				dark_button = ui.button(icon='dark_mode', on_click=lambda: [darkness.set_value(True), update_tooltip(dark_button, 'be Dark')]) \
					.props('flat fab-mini').tooltip('be Dark').bind_visibility_from(darkness, 'value', value=False)
				light_button = ui.button(icon='light_mode', on_click=lambda: [darkness.set_value(False), update_tooltip(light_button, 'be Light')]) \
					.props('flat fab-mini').tooltip('be Light').bind_visibility_from(darkness, 'value', value=True)

			chat_settings = ui.button(icon='settings', on_click=lambda: chat_settings_dialog()) \
			.tooltip("Chat    Settings") \
			.props('no-caps flat fab-mini')

			def reload_app(user_session, user_settings):
				# ui.run_javascript("setTimeout(function() { window.location.replace(window.location.href); }, 1000);")
				ui.run_javascript("location.reload(true);")
				# ui.run_javascript("""
				# if (navigator.userAgent.includes('Safari') && !navigator.userAgent.includes('Chrome')) {
				#     setTimeout(function() { location.reload(true); }, 1000);
				# } else {
				#     setTimeout(function() { window.location.replace(window.location.href); }, 1000);
				# }
				# """)

			ui.button(icon='restart_alt', on_click=lambda: reload_app(user_session, user_settings)) \
			.tooltip("Reload app") \
			.props('no-caps flat fab-mini')

			ui.button(icon='memory', on_click=lambda: ui.notify(print_memory_usage())) \
			.tooltip("memory usage") \
			.props('no-caps flat fab-mini')

			ui.button(
				icon='logout',
				on_click=lambda: ui.navigate.to('/google/logout')
			) \
			.tooltip("Logout") \
			.props('no-caps flat fab-mini')


			# this only appears during long streaming responses:
			user_session.abort_stream = ui.button(
				icon='content_cut',
				on_click=lambda e: set_abort(True)
			) \
			.tooltip("stop AI's response") \
			.props('flat outline round color=red').classes('shadow-lg')

			user_session.abort_stream.set_visibility(False)


	# the app's heart and raison d'etre ...
	# which contains the text generated responses from LLMs of AI providers:
	with ui.element('div').classes('flex flex-col min-h-full w-full mx-auto'):
		user_session.message_container = (
			ui.element("div")
			.classes(
				"w-full overflow-auto p-2 rounded flex-grow"
			)
			.props('id="scrollable"')
			.style(f'height: {wih}px; font-size: 15px !important; white-space: pre-wrap;') 
		)
		ui.separator().props("size=4px color=primary")  # insinuate bottom of chat history
		

	def check_splashed_and_providers():
		if user_session.splashed:
			if len(user_session.providers) - 1 <= 0:
				ui.html('<style>.multi-line-notification { white-space: pre-line; }</style>')
				ui.notification(
					'*** No AI providers are available! *** \n'
					'Please click on Chat Settings to add/change AI provider \n'
					'API keys, or if you are using Ollama or LM Studio  \n'
					'ensure both/either are up before starting this app. \n'
					"'Chat Settings' is the gear icon in the button bar below.",
					multi_line=True,
					classes='multi-line-notification',
					type='negative', 
					close_button="⬇️ click red gear to fix",
					position='top',
					timeout=0 # wait for user to click close_button
				)
				chat_settings.props('color=negative')
				chat_settings.tooltip('Chat 😱 Settings')
				chat_settings.update()  # refresh the UI to reflect changes

			splash_timer.cancel()

	# await asyncio.sleep(3)
	splash_timer = ui.timer(2, check_splashed_and_providers)


	async def chat_settings_dialog():
		with ui.dialog() as settings_popup:
			settings_popup.props("persistent")
			settings_popup.props("maximized")
			with settings_popup, ui.card().classes("w-full items-center"):
				with ui.column():
					with ui.row().classes("w-full items-center mb-0.1 space-x-2"):
						ui.space()
						ui.label('Keys2Text Settings').style("font-size: 20px; font-weight: bold").classes("m-0")

						def save_settings(dark_mode_switch, primary_color, provider_inputs):
							user_settings.settings_updated = True
							user_settings.darkness = dark_mode_switch.value
							user_settings.current_primary_color = primary_color
							for provider, inputs in provider_inputs.items():
							  for key, key_object in inputs.items():
								  if key == 'timeout':
									  user_settings.set_provider_setting(provider, key, convert_to_int(key_object.value, None), user_settings.settings_response)
								  else:
									  user_settings.set_provider_setting(provider, key, key_object.value, user_settings.settings_response)
							ui.notify('Settings saved, but the changes only apply after reloading the app.', position="top", color='warning')
							chat_settings.props('color=primary')
							chat_settings.tooltip(f"Chat Settings")
							chat_settings.update()  # refresh the UI to reflect changes

							user_settings.save_as_json_file(user_session)

						ui.space()
						ui.button(icon='save_as', on_click=lambda: save_settings(
							dark_mode_switch,
							get_primary_color(),
							provider_inputs
						)).tooltip("Save settings").props('no-caps flat dense')

						async def close_clear_dialog():
							settings_popup.close()
							settings_popup.clear() # removes the hidden settings_popup ui.dialog

						ui.button(
							icon='close', 
							on_click=close_clear_dialog
							) \
							.tooltip("Close") \
							.props('no-caps flat fab-mini')

					with ui.column().classes('mb-2'):
						with ui.row().classes('w-full items-center'):
							dark_light = darkness.value
							ui.label('Light or Dark').classes('ml-2 mr-0')
							dark_mode_switch = ui.switch(value=dark_light).classes('ml-0').tooltip("select light or dark mode")

							def set_primary_color(color):
								user_settings.current_primary_color = color
								js_code = f"""
								document.getElementById('picker').style.setProperty('color', '{color}', 'important');
								"""
								ui.run_javascript(js_code)

							def get_primary_color():
								return user_settings.current_primary_color

							with ui.button(icon='palette').props('id=picker').props('no-caps flat fab-mini').classes('ml-4').tooltip("change color, note: changes only applied after restarting app") as button:
								button = ui.color_picker(on_pick=lambda e: set_primary_color(e.color))
								button.q_color.props('''default-view=palette no-header no-footer :palette="['#6200ea', '#ff0000', '#ff8000', '#d6d600', '#4CAF50', '#00a3a3', '#007bf5', '#7b00f5', '#d600d6', '#333333']"''')

					with ui.row().classes('w-full items-center'):
						ui.label('Provider Settings:').style('font-size: 18px; font-weight: bold; margin-bottom: 8px;')
						ui.space()
						ui.label("* be careful as these settings contain API keys, i.e. money!").style('font-size: 12px; font-style: italic; margin-bottom: 8px; color: #546e7a;')

						provider_inputs = {}
						with ui.column().classes('w-full'):
							for provider_name in user_settings.provider_settings:
								with ui.expansion(provider_name).classes('w-full mb-2'):
									with ui.column().classes('w-full'):
										inputs = {}
										inputs['api_key'] = ui.input(
											label='API Key', 
											password=True, 
											password_toggle_button=True, 
											value=user_settings.get_provider_setting(provider_name, 'api_key')) \
										.classes('w-full mb-2') \
										.props("spellcheck=false") \
										.props("autocomplete=off") \
										.props("autocorrect=off")

										inputs['timeout'] = ui.input(
											label='Timeout', 
											value=user_settings.get_provider_setting(provider_name, 'timeout')) \
										.classes('w-full mb-2') \
										.props("spellcheck=false") \
										.props("autocomplete=off") \
										.props("autocorrect=off")

										if provider_name in ['Ollama', 'OpenRouter', 'LMStudio']:
											inputs['base_url'] = ui.input(
												label='Base URL', 
												value=user_settings.get_provider_setting(provider_name, 'base_url')) \
											.classes('w-full mb-2') \
											.props("spellcheck=false") \
											.props("autocomplete=off") \
											.props("autocorrect=off")

										if provider_name == 'Anthropic':
											inputs['max_tokens'] = ui.input(
												label='Max Tokens', 
												value=user_settings.get_provider_setting(provider_name, 'max_tokens')) \
											.classes('w-full mb-2') \
											.props("spellcheck=false") \
											.props("autocomplete=off") \
											.props("autocorrect=off")

										provider_inputs[provider_name] = inputs

							ui.separator().props("size=4px color=primary") # insinuate bottom of settings

		settings_popup.open()


	# *******************************************************
	# after doing: session, settings, ui; but before splash, 
	# try to get the local (ollama / lmstudio) models if any:
	# *******************************************************

	# note: because the:
	#   ui.run_javascript(f'listModels ...
	# was being run inside of all of this:
	#   model_count = await ollama_models()
	#   append_splash_text(model_log, providers_models, f"\tOllama offers {omodels_count} models.")
	#   def sync_handle_models_list():
	#       asyncio.run(handle_models_list())
	# ... often the following error happened:
	#   IndexError: pop from empty list
	# ... which has something to do with nicegui's containers and slots,
	# and the same happened for LMStudio,
	# so while this code is messyand redundant, it works, so far:
	pm = "Ollama"
	omodels = None
	omodels_count = 0
	try:
		provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
		if not provider_api_key or provider_api_key.strip() == "":
			if user_session.providers and pm in user_session.providers:
				provider_api_key = 'ollama' # no api_key is required, so force it
				# user_session.providers.remove(pm)
		provider_base_url = user_settings.get_provider_setting(pm, 'base_url')
		if not provider_base_url or provider_base_url.strip() == "":
			if user_session.providers and pm in user_session.providers:
				user_session.providers.remove(pm)
		try:
			provider_base_url = provider_base_url.removesuffix("/")
			models_url = f"{provider_base_url}{user_session.openai_compat_models_endpoint}"
			omodels = await ui.run_javascript(
				f'listModels("{models_url}", "{provider_api_key}")', 
				timeout=2.0
			)
		except Exception as e:
			print(f"Error fetching Ollama models: {e}")
			if user_session.providers and pm in user_session.providers:
				user_session.providers.remove(pm)
		# validate and process omodels if any:
		if isinstance(omodels, dict):
			if 'data' in omodels and isinstance(omodels['data'], list):
				chat_omodels = [model['id'] for model in omodels['data'] if isinstance(model, dict) and 'id' in model]
				user_settings.provider_models[pm] = chat_omodels
				omodels_count = len(chat_omodels)
			else:
				if user_session.providers and pm in user_session.providers:
					user_session.providers.remove(pm)
		else:
			# print(f"Ollama models is not a dict: {type(omodels)}")
			if user_session.providers and pm in user_session.providers:
				user_session.providers.remove(pm)
	except Exception as e:
		print(f"Error while fetching Ollama models: {e}")
		if user_session.providers and pm in user_session.providers:
			user_session.providers.remove(pm)

	pm = "LMStudio"
	lmsmodels = None
	lmsmodels_count = 0
	try:
		provider_api_key = user_settings.get_provider_setting(pm, 'api_key')
		if not provider_api_key or provider_api_key.strip() == "":
			if user_session.providers and pm in user_session.providers:
				provider_api_key = 'lmstudio' # no api_key is required, so force it
				# user_session.providers.remove(pm)
		provider_base_url = user_settings.get_provider_setting(pm, 'base_url')
		if not provider_base_url or provider_base_url.strip() == "":
			if user_session.providers and pm in user_session.providers:
				user_session.providers.remove(pm)
		try:
			provider_base_url = provider_base_url.removesuffix("/")
			models_url = f"{provider_base_url}{user_session.openai_compat_models_endpoint}"
			lmsmodels = await ui.run_javascript(
				f'listModels("{models_url}", "{provider_api_key}")', 
				timeout=2.0
			)
		except Exception as e:
			print(f"Error fetching LMStudio models: {e}")
			if user_session.providers and pm in user_session.providers:
				user_session.providers.remove(pm)
		# validate and process lmsmodels if any:
		if isinstance(lmsmodels, dict):
			if 'data' in lmsmodels and isinstance(lmsmodels['data'], list):
				chat_lmsmodels = [model['id'] for model in lmsmodels['data'] if isinstance(model, dict) and 'id' in model]
				user_settings.provider_models[pm] = chat_lmsmodels
				lmsmodels_count = len(chat_lmsmodels)
			else:
				if user_session.providers and pm in user_session.providers:
					user_session.providers.remove(pm)
		else:
			# print(f"LMStudio models is not a dict: {type(lmsmodels)}")
			if user_session.providers and pm in user_session.providers:
				user_session.providers.remove(pm)
	except Exception as e:
		print(f"Error while fetching LMStudio models: {e}")
		if user_session.providers and pm in user_session.providers:
			user_session.providers.remove(pm)


	async def handle_models_list():
		append_splash_text(model_log, providers_models, f'Gathering AI models for each provider . . .')
		append_splash_text(model_log, providers_models, f"* Providers that require an API key:")
		model_count = await anthropic_models()
		append_splash_text(model_log, providers_models, f"\tAnthropic offers {model_count} models.")
		model_count = await google_models()
		append_splash_text(model_log, providers_models, f"\tGoogle AI Studio offers {model_count} models.")
		model_count = await groq_models()
		append_splash_text(model_log, providers_models, f"\tGroq offers {model_count} models.")
		model_count = await openai_models()
		append_splash_text(model_log, providers_models, f"\tOpenAI offers {model_count} models.")
		model_count = await openrouter_models()
		append_splash_text(model_log, providers_models, f"\tOpenRouter offers {model_count} models.")

		append_splash_text(model_log, providers_models, f"\n* Without API key and/or local models:")
		model_count = await duckduckgo_models()
		append_splash_text(model_log, providers_models, f"\tDuckDuckGo offers {model_count} models.")
		append_splash_text(model_log, providers_models, f"\tLM Studio offers {lmsmodels_count} models.")
		append_splash_text(model_log, providers_models, f"\tOllama offers {omodels_count} models.")

	def sync_handle_models_list():
		asyncio.run(handle_models_list())

	if not user_session.splashed:
		await asyncio.sleep(1.0)
		# seems to fix the sometimes long/varying response times from providers:
		await run.io_bound(sync_handle_models_list)

		user_session.total_models = sum(len(models) for models in user_settings.provider_models.values())
		# ignore this app's pretend model stuff:
		ignored = len(user_settings.provider_models["Keys2Text"])
		total_ai_providers = len(user_session.providers) - 1 # ignore this app's pretend provider
		total_ai_models = user_session.total_models - ignored
		append_splash_text(model_log, providers_models, f"\nWith {total_ai_models} models available from {total_ai_providers} providers.")
		append_splash_text(model_log, providers_models, f"Enjoy!")
		await asyncio.sleep(1)
		user_session.splash_dialog.close()
		user_session.splash_dialog.clear() # removes the hidden splash ui.dialog

		user_session.ui_select_provider.options = user_session.providers  # update the options in the select element
		# user_session.ui_select_provider.props(f'label="{len(user_session.providers) - 1} Providers:"')
		user_session.ui_select_provider.update()  # refresh the UI to reflect changes

		# because of nicegui's webserver-ness(fastapi/uvicorn); let's remember we splashed already:
		user_session.splashed = True
		# annoying = ui.notify("See full list of models by using Keys2Text > Vitals.", position='bottom')

