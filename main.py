# uvicorn main:app --workers 1 --host 127.0.0.1 --port 3000
# 
# https://docs.render.com/deploy-fastapi
#   https://keypoints-oc6g.onrender.com = BASE_URL
#   uvicorn main:app --workers 1 --host 0.0.0.0 --port $PORT
# 
# start ollama like this:
# OLLAMA_ORIGINS="http://127.0.0.1,https://app.novelcrafter.com" ollama serve
import frontend
from frontend import *

import os
import time
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from starlette.config import Config
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import HTMLResponse, RedirectResponse
from authlib.integrations.starlette_client import OAuth, OAuthError

import psutil
import gc

# from memory_profiler import start_memory_tracking
# start_memory_tracking()

# from icecream import ic
# ic.configureOutput(includeContext=True, contextAbsPath=True)


def print_memory_usage():
	process = psutil.Process()
	memory_info = process.memory_info()
	memory_usage_mb = memory_info.rss / (1024 * 1024)
	mum = f"Memory usage: {memory_usage_mb:.2f} MB"
	return mum


# this 'app' is global to all users:
app = FastAPI() # different from nicegui's "app"

app.add_middleware(
	CORSMiddleware,
	# allow_origins=["*"], # bad! so be more restrictive:
	allow_origins=["http://localhost:3000", "https://keys2text-chat.onrender.com"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

# SessionMiddleware, OAuth, Authlib stuff, this is also app/global

config = Config(".env") # starlette.config

APP_ENV = config.get("APP_ENV", default="local") # set to production on Render.com

# base_url = config("BASE_URL")
# secret_key = config("SECRET_KEY")
# google_client_id = config("GOOGLE_CLIENT_ID")
# google_client_secret = config("GOOGLE_CLIENT_SECRET")
# storage_secret = config("STORAGE_SECRET")

app.add_middleware(SessionMiddleware, secret_key=config("SECRET_KEY"))

oauth = OAuth(config)
CONF_URL = 'https://accounts.google.com/.well-known/openid-configuration'
oauth.register(
	name='google',
	server_metadata_url=CONF_URL,
	client_kwargs={
		'scope': 'openid email profile',
		# instead of using the previously signed in account, 
		# force the user to select an account when signing/logging in,
		# which of course can be the previously signed in account ... 
		# i.e. the: "Sign in with Google" page appears:
		# 'prompt': 'select_account',
	}
)

# FastAPI endpoints to auth via Google's SSO and maintain request.session

@app.get('/google/callback')
async def auth(request: Request):
	# print(f"\nauth: app={app}\n")
	user = None
	try:
		token = await oauth.google.authorize_access_token(request)
		user = token.get('userinfo')
		user_sub = user.get("sub") # a better user id via google
	except OAuthError as oae:
		return HTMLResponse(f'<h1>Authentication failed: {oae.error}</h1>')
	if user:
		request.session['gootoken'] = token
		request.session['userlastsignin'] = int(time.time()) # current time in seconds
	response = RedirectResponse(url='/')
	return response


@app.get('/google/login')
async def google_login(request: Request, prompt: str = None):
	redirect_uri = request.url_for('auth') # url is from google, i.e. /google/callback
	client = oauth.create_client('google')
	if prompt == 'select_account':
		return await client.authorize_redirect(request, redirect_uri, prompt='select_account')
	else:
		return await client.authorize_redirect(request, redirect_uri)


@app.get('/google/logout')
async def logout(request: Request):
	response = RedirectResponse(url='/') # user sees Sign in with Google
	request.session.clear()
	response.delete_cookie(key='session')
	return response


@app.post('/user/disconnect')
async def user_disconnect(request: Request):
	# which happens when a user closes a tab in the browser, quits the browser, and 
	# during Google's SSO flow: beginning with 'GET /google/login' as the flow 
	# navigates away from this app's URL to google's URL.
	# data = await request.json()
	# user_id = data.get('userId')
	# maybe do something with user_id = like what???
	# is it worth logging their last visit session date/time???

	# Dec 22, 2024 none of the following helps with memory growth?
	print(f"before gc.collect = {print_memory_usage()}")
	gc.collect()
	time.sleep(0.1)
	print(f"after gc.collect + sleep = {print_memory_usage()}")


frontend.init(config("SECRET_KEY"), app)

if __name__ == '__main__':
	print("start it this way:")
	print("uvicorn main:app --workers 1 --host localhost --port 3000")
