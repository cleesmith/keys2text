import os
import sys
import json
import re
from datetime import datetime
import time
from typing import List, Tuple
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from google.oauth2 import id_token
import google.auth.transport.requests

import httpx

from nicegui import app, ui, run, Client, events
from nicegui import __version__ as nv

from user_session_settings import UserSession
from user_session_settings import UserSettings

import keys2text
from keys2text import *

import random
import string

import base64
import hmac
import hashlib
from dotenv import load_dotenv
from cryptography.fernet import Fernet

# from icecream import ic
# ic.configureOutput(includeContext=True, contextAbsPath=True)

# from memory_profiler import print_top_allocations


# WARNING! developer must set: APERITIF using gen_key.py
# load environment variables (works with .env file or system environment)
load_dotenv()
APERITIF = os.getenv('APERITIF')
SAMBUCA = Fernet(APERITIF)


def init(secret_key, fastapi_app: FastAPI):
    ui.run_with(
        fastapi_app,
        # mount_path='/', # this makes the paths passed to @ui.page accessible from the root
        storage_secret=secret_key,
        favicon="static/daemon.png",
        title="Keys2Text - chat using API keys",
        dark=True,
        show_welcome_message=False,
        reconnect_timeout=30,
    )

def generate_random_websocket_name():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8))


class GoogleAuthManager:
    async def google_login_needed(self, token):
        # google account users can revoke their connection to this app, see:
        # https://myaccount.google.com/connections 
        # ... which allows users to:
        #   "Keep track of your connections
        #    You shared data with these third-party apps and services."
        #   ... then a user can click on a third-party app to:
        #   "Delete all connections you have with Keys2Text
        #    You can delete the access you’ve given to Keys2Text and Google"
        # note: revocation is not instant, it can take a while for the google behemoth to act
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    'https://oauth2.googleapis.com/tokeninfo', 
                    params={'id_token': token}
                )
                if response.status_code != 200:
                    print("!!! Token is invalid or revoked")
                    return True
                print("*** Token is valid:", response.json())
                return False
        except Exception as e:
            print(e)
            return True


@ui.page('/', response_timeout=999)
async def home(request: Request, client: Client):
    gootoken = request.session.get('gootoken', None)
    user = None
    if gootoken:
        user = gootoken.get('userinfo', None)
        user_sub = user.get("sub", None) # a better user id via google

    # ??? something about doing this causes issues with other ui.run_javascript's ???
    # await client.connected()
    # ui.run_javascript(f"""
    #     window.addEventListener('beforeunload', function(event) {{
    #         navigator.sendBeacon('/user/disconnect');
    #     }});
    # """)

    auth_manager = GoogleAuthManager()

    user_id = request.session.get('id') # most reliable
    # print(user_id, ui.context.client.id)

    if not user:
        # user needs to auth and sign in
        ui.navigate.to('/google/login?prompt=select_account')
        # with ui.element('div').classes('h-screen w-screen flex justify-center items-center'):
        #     with ui.card().classes('w-full max-w-md text-center flex flex-col items-center justify-center p-8'):
        #         ui.label("Keys2Text Chat").classes("text-2xl font-bold mb-5 mt-5")
        #         ui.label("Sign in\nto continue to Keys2Text").classes("text-xl font-bold mb-4 w-full text-left").style("white-space: pre-line;")
        #         with ui.button(
        #                 on_click=lambda: ui.navigate.to('/google/login?prompt=select_account')
        #             ) \
        #             .props('no-caps flat fab-mini') \
        #             .classes('ml-4') \
        #             .tooltip("Sign in with Google") as button:
        #                 ui.image('https://www.slipthetrap.com/images/google_sso_login.png').classes('w-64 mb-6')
    else:
        # rely on a better user id via google = 'sub', 
        # assigned by google, and same for all apps,
        # and can be used for .json files which are more permanent than cookies,
        # and encrypted but are they 'permanent' between Render.com deploys = yes (tested)
        # print(request.session)

        user_id = request.session.get('id') # .get is most reliable

        # access_token = request.session.get('access_token')
        # refresh_token = request.session.get('refresh_token')
        # these were set during auth via '/google/callback':
        gootoken = request.session.get('gootoken')
        userlastsignin = request.session.get('userlastsignin', 0)

        # the following code works, but happens too frequently, like every hour, 
        # so maybe a better approach is to have a 2 week timeout in user_settings 
        # then force a signout, then a signin auth with google's SSO:
        # id_token = gootoken.get('id_token', None)
        # print(id_token)
        # re_auth_needed = await auth_manager.google_login_needed(id_token)
        # print(re_auth_needed)
        # if re_auth_needed:
        #     ui.navigate.to('/google/login?prompt=select_account')

        user_session = UserSession()
        user_session.client_ip = client.ip
        user_session.users_google_sub = user.get("sub")
        user_session.path_to_settings = f"/var/data/{user_session.users_google_sub}.json"
        user_session.session_id = request.session
        user_session.sambuca = SAMBUCA

        user_settings = UserSettings()
        user_settings.users_google_sub = user_session.users_google_sub
        user_settings.path_to_settings = user_session.path_to_settings

        user_settings.load_from_json_file(user_session)

        user_session.providers = user_settings.providers # initially it's all providers

        user_session.google_picture = user.get("picture")
        user_session.google_given_name = user.get("given_name")
        user_session.google_family_name = user.get("family_name")
        user_session.google_email = user.get("email")
        user_session.google_email_verified = user.get("email_verified")

        user_settings.google_picture = user_session.google_picture
        user_settings.google_given_name = user_session.google_given_name
        user_settings.google_family_name = user_session.google_family_name
        user_settings.google_email = user_session.google_email
        user_settings.google_email_verified = user_session.google_email_verified
        user_settings.users_google_sub = user_session.users_google_sub
        user_settings.path_to_settings = user_session.path_to_settings
        user_settings.session_id = user_session.session_id
        user_settings.websocket_name = f"/{generate_random_websocket_name()}"

        if user_settings.signin_time == userlastsignin:
            # no need to update and save
            pass
        else:
            # probably coz of initial signin or re-signin due to expiration
            user_settings.signin_time = userlastsignin # via '/google/callback'
            user_settings.save_as_json_file(user_session)
        current_time = int(time.time())
        elapsed_time_since_last_signin_seconds = current_time - user_settings.signin_time
        needs_signin = elapsed_time_since_last_signin_seconds >= user_session.signin_timeout
        if needs_signin:
            # user needs to auth and sign in, again
            ui.navigate.to('/google/login?prompt=select_account')


        def client_disconnect(user_session, user_settings):
            # remove any 'long living' vars to help garbage collection, and 
            # most of the app's vars are in these:
            user_session = None
            user_settings = None
            # Dec 22, 2024 none of the following helps with memory growth?
            # print(f"*** frontend.py: client_disconnect: gc.collect = {print_memory_usage()}")
            # gc.collect()
            # print_top_allocations()


        # ui.context.client.on_disconnect(lambda: client_disconnect(user_session, user_settings))
        app.on_disconnect(lambda: client_disconnect(user_session, user_settings))


        await keys2text(request, client, ui, user_session, user_settings)

