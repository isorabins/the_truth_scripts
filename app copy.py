import os
import requests
import json
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt import App as SlackApp
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
import tiktoken
import threading
import time
import subprocess
import logging
from logging.handlers import RotatingFileHandler

# Setup logging
log_dir = '/Users/isorabins/Desktop/GPT_AI/slack_bot_the_truth'
log_file_path = os.path.join(log_dir, 'flask_app.log')

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)
logger.debug("This is a test debug message to check logging functionality.")

# Load environment variables from .env file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path)

# Define global variables
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
SLACK_BOT_USER_ID = os.getenv("SLACK_BOT_USER_ID")
CANOPY_API_URL = os.getenv("CANOPY_API_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("INDEX_NAME")
json_file_path = os.path.join(BASE_DIR, 'data', 'conversation_history.json')

# Log the successful loading of API keys and other sensitive variables without exposing their values
logger.info("SLACK_BOT_TOKEN loaded successfully.")
logger.info("SLACK_SIGNING_SECRET loaded successfully.")
logger.info("SLACK_BOT_USER_ID loaded successfully.")
logger.info("CANOPY_API_URL loaded successfully.")
logger.info("OPENAI_API_KEY loaded successfully.")
logger.info("PINECONE_API_KEY loaded successfully.")
logger.info("INDEX_NAME loaded successfully.")

# Raise an error if INDEX_NAME is not set
if not INDEX_NAME:
    logger.error("INDEX_NAME is not set. Please set the INDEX_NAME environment variable.")
    raise ValueError('INDEX_NAME must be provided. Either pass it explicitly or set the INDEX_NAME environment variable')

# Initialize the Slack app
slack_app = SlackApp(token=SLACK_BOT_TOKEN)

# Initialize the Flask app
flask_app = Flask(__name__)
CORS(flask_app)  # Enable CORS on the Flask app
handler = SlackRequestHandler(slack_app)

logger.info("Flask and Slack apps have been initialized.")

@flask_app.route('/health')
def health():
    logger.info("Health check endpoint was accessed.")
    return "Health OK", 200

if not os.path.exists(json_file_path):
    with open(json_file_path, 'w') as file:
        json.dump([], file)

def count_tokens(text, model="gpt-3.5-turbo"):
    enc = tiktoken.encoding_for_model(model)
    return len(enc.encode(text))

def trim_conversation_context(conversation_history, max_tokens=4000, model="gpt-3.5-turbo"):
    total_tokens = sum(count_tokens(msg["content"], model) for msg in conversation_history)
    while total_tokens > max_tokens and len(conversation_history) > 1:
        removed_msg = conversation_history.pop(0)
        total_tokens -= count_tokens(removed_msg["content"], model)
    return conversation_history

def manage_json_file(json_file_path, max_tokens=1000):
    with open(json_file_path, 'r+') as file:
        try:
            conversation_history = json.load(file)
        except json.JSONDecodeError:
            conversation_history = []

        total_tokens = sum(count_tokens(msg["content"]) for msg in conversation_history)
        while total_tokens > max_tokens and len(conversation_history) > 1:
            removed_msg = conversation_history.pop(0)
            total_tokens -= count_tokens(removed_msg["content"])
        
        file.seek(0)
        file.truncate()
        json.dump(conversation_history, file, indent=4)
        file.flush()

def update_json_file(user_input, bot_response):
    with open(json_file_path, 'r+') as file:
        try:
            conversation_history = json.load(file)
        except json.JSONDecodeError:
            conversation_history = []

        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": bot_response})
        
        file.seek(0)
        file.truncate()
        json.dump(conversation_history, file, indent=4)
        file.flush()
        
        manage_json_file(json_file_path)

def get_conversation_context():
    with open(json_file_path, 'r') as file:
        try:
            conversation_history = json.load(file)
        except json.JSONDecodeError:
            conversation_history = []
    return conversation_history

def log_unanswered_question(question):
    log_file_path = "unanswered_questions.txt"
    with open(log_file_path, 'a') as file:
        file.write(question + "\n")

def send_to_canopy(query):
    custom_prompt = """You are a helpful assistant for forageSF. Your job is to help anyone who has a question
        about our data. Always respond in an upbeat and friendly way, and ensure your answers are 
        informative and supportive. When you provide an answer, also include a quote of the specific 
        content you used to arrive at your answer. """
    modified_query = f"{custom_prompt} {query}"
    context = get_conversation_context()
    context = trim_conversation_context(context, max_tokens=4054)

    payload = {
        "messages": context + [{"role": "user", "content": modified_query}],
        "stream": False,
        "model": "GPT-4",
        "frequency_penalty": 0,
        "logit_bias": {},
        "max_tokens": 0,
        "n": 1,
        "presence_penalty": 0,
        "response_format": {},
        "seed": 0,
        "stop": [],
        "temperature": 0,
        "top_p": 1,
        "user": "string"
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }

    try:
        response = requests.post(CANOPY_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        if "choices" in response_data and len(response_data["choices"]) > 0:
            message_content = response_data["choices"][0]["message"]["content"]
            return message_content
        else:
            return "Error: Unexpected response format from Canopy server"
    except requests.exceptions.RequestException as e:
        print(f"Error communicating with Canopy server: {e}")
        return "Error: Could not get a response from the Canopy server"

@slack_app.event("app_mention")
def handle_mentions(body, say):
    text = body["event"]["text"]
    mention = f"<@{SLACK_BOT_USER_ID}>"
    text = text.replace(mention, "").strip()

    response = send_to_canopy(text)
    update_json_file(text, response)
    say(response)

@slack_app.event("message")
def handle_message_events(body, logger):
    logger.info(body)

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    try:
        data = request.get_json()
        print(f"Received data: {data}")
        if "challenge" in data:
            return jsonify({'challenge': data['challenge']})
        return handler.handle(request)
    except Exception as e:
        print(f"Error handling request: {e}")
        return jsonify({"error": "Error processing request"}), 400

# Run the Flask app
if __name__ == "__main__":
    flask_app.run(port=3000)
