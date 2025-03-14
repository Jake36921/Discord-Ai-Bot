import discord
import requests
import yaml
import json
import time
import re
import base64
import aiohttp
import io
from PIL import Image

# Load stuff from config.yaml
try:
    with open("config.yaml", "r", encoding='utf-8') as f:
        keys = yaml.safe_load(f)
        openai_url = keys.get("openai_url")
        discord_token = keys.get("discord_token")
        temperature = keys.get("temperature", 0.7)
        context_size = keys.get("context_size", 4096)
        output_size = keys.get("output_size", 512)
        conversation_timeout = keys.get("conversation_timeout", 60)  # Default 60 seconds (1 minute)
        backread_message_count = keys.get("backread_message_count", 3) # Default backread 3 messages
        sysprompt = keys.get("system_prompt", " ")
        emoji_prompt = keys.get("emoji_prompt", "")
        example_dialogue = keys.get("example_dialogue", "")
        persona = keys.get("persona", "")
        vision = keys.get("vision", False)
        max_image_size = keys.get("max_image_size", 2 * 1024 * 1024)  # Default 2MB max size
        max_image_dimension = keys.get("max_image_dimension", 2048)  # Default 2048px
    
    if not openai_url or not discord_token:
        raise ValueError("Missing 'openai_url' or 'discord_token' in config.yaml")
except FileNotFoundError:
    print("Error: config.yaml not found. Please create config.yaml with 'openai_url' and 'discord_token'.")
    exit()
except yaml.YAMLError as e:
    print(f"Error parsing config.yaml: {e}")
    exit()
except ValueError as e:
    print(f"Error loading keys from config.yaml: {e}")
    exit()


system_prompt = sysprompt + emoji_prompt #replace sysprompt with persona for something less dull {configure it in config.yaml}

try:
    print(f"Url: {openai_url}, Discord Token: {discord_token}, Temperature: {temperature}, Context_Size: {context_size}, Output Size: {output_size}, Conversation Timeout: {conversation_timeout}, Backread amount: {backread_message_count}, Vision enabled: {vision}")
except Exception as e:
    print("An error occurred:", e)


intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
client = discord.Client(intents=intents)


conversation_history = {} 
last_interaction_time = {}

def get_string_between_reacts(text):
    pattern = re.compile(r'!react(.*?)!react')
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return None

async def process_image(attachment):
    if not vision:
        return None
    
    try:
        image_bytes = await attachment.read()
        if len(image_bytes) > max_image_size:

            img = Image.open(io.BytesIO(image_bytes))
            

            output = io.BytesIO()
            img.save(output, format=img.format if img.format else 'JPEG', quality=85)
            image_bytes = output.getvalue()
            
        return base64.b64encode(image_bytes).decode('utf-8')
    
    except Exception as e:
        print(f"Error processing image: {e}")
        return None


async def ask_openai(user_id, prompt, backread_context="", attachment=None):
    headers = {
        'Content-Type': 'application/json',
    }
    

    if user_id not in conversation_history:
        conversation_history[user_id] = [{"role": "system", "content": system_prompt}]
    
    current_history = conversation_history[user_id]


    if backread_context:
        current_history.append({
            "role": "system",
            "content": "Recent channel messages for context:\n" + backread_context
        })


    user_message = {"role": "user"}
    content_parts = []
    

    if prompt:
        content_parts.append({
            "type": "text",
            "text": prompt
        })
    

    image_base64 = None
    if attachment and vision:
        try:
            image_base64 = await process_image(attachment)
            
            if image_base64:
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/{attachment.content_type.split('/')[-1]};base64,{image_base64}"
                    }
                })
            else:
                print("Failed to process image or image processing is disabled")
        except Exception as e:
            print(f"Error processing image attachment: {e}")
    

    if len(content_parts) > 1:
        user_message["content"] = content_parts
    else:
        user_message["content"] = prompt
    current_history.append(user_message)
    data = {
        "messages": current_history,
        "temperature": temperature,
        "max_tokens": output_size
    }
    if context_size:
        data["context_window"] = context_size
    try:
        response = requests.post(openai_url, headers=headers, json=data)
        response.raise_for_status()
        response_json = response.json()

        if 'choices' in response_json and response_json['choices']:

            if ('message' in response_json['choices'][0] and
                'content' in response_json['choices'][0]['message']):
                ai_response_text = response_json['choices'][0]['message']['content']
                conversation_history[user_id].append({"role": "assistant", "content": ai_response_text})
                return ai_response_text

            elif 'text' in response_json['choices'][0]:
                ai_response_text = response_json['choices'][0]['text']
                conversation_history[user_id].append({"role": "assistant", "content": ai_response_text})
                return ai_response_text
            else:
                return "I received a response, but couldn't extract the text. Please check the API response format."
        else:
            return "I couldn't understand the response from the API. Please check the API response format."

    except requests.exceptions.RequestException as e:
        print(f"Error communicating with OpenAI API: {e}")
        return "Trouble connecting to the API right now."
    except json.JSONDecodeError:
        print("Error: OpenAI API response was not valid JSON.")
        return "The API returned an unexpected response."
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return "An unexpected error occurred."


@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    user_id = message.author.id
    channel = message.channel
    

    current_time = time.time()
    if user_id in last_interaction_time and current_time - last_interaction_time[user_id] > conversation_timeout:
        if user_id in conversation_history:
            del conversation_history[user_id]
            await message.channel.send(f"<@{user_id}>, conversation timed out. Please ping me again to start a new conversation.")
    

    image_attachment = None
    if message.attachments and vision:
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith('image/'):
                image_attachment = attachment
                print(f"Processing image: {attachment.filename} ({attachment.content_type})")
                break

    if client.user in message.mentions:
        user_prompt = message.content.replace(f'<@{client.user.id}>', '').strip()
        if not user_prompt and user_id in conversation_history and len(conversation_history[user_id]) > 1:
            user_prompt = "continue the conversation"

        if not user_prompt and not image_attachment:
            await message.reply("Yes? Please ask me something or share an image to discuss.")
            return
        backread_messages_str = await get_backread_context(channel, message, backread_message_count)


        async with message.channel.typing():
            openai_response = await ask_openai(user_id, user_prompt, backread_messages_str, image_attachment)
            await process_and_send_response(message, openai_response)
        
        last_interaction_time[user_id] = current_time
        
    elif message.reference and message.reference.resolved and message.reference.resolved.author == client.user:
        user_prompt = message.content.strip()
        
        if not user_prompt and not image_attachment:
            await message.reply("Please write a message or share an image to reply with.")
            return
        backread_messages_str = await get_backread_context(channel, message, backread_message_count)

        async with message.channel.typing():
            openai_response = await ask_openai(user_id, user_prompt, backread_messages_str, image_attachment)
            await process_and_send_response(message, openai_response)
        
        last_interaction_time[user_id] = current_time
        
    elif user_id in last_interaction_time and current_time - last_interaction_time[user_id] <= conversation_timeout and user_id in conversation_history:
        user_prompt = message.content.strip()

        if not user_prompt and not image_attachment:
            return 


        backread_messages_str = await get_backread_context(channel, message, backread_message_count)


        async with message.channel.typing():
            openai_response = await ask_openai(user_id, user_prompt, backread_messages_str, image_attachment)
            await process_and_send_response(message, openai_response)
        
        last_interaction_time[user_id] = current_time


async def get_backread_context(channel, current_message, limit):
    backread_messages_str = ""
    try:
        async for past_message in channel.history(limit=limit + 1):
            if past_message != current_message:
                attachment_info = ""
                if past_message.attachments:
                    for attachment in past_message.attachments:
                        if attachment.content_type and attachment.content_type.startswith('image/'):
                            attachment_info = " [shared an image]"
                            break
                
                backread_messages_str = f"{past_message.author.name}{attachment_info}: {past_message.content}\n" + backread_messages_str
    except discord.errors.Forbidden:
        backread_messages_str = "Could not retrieve recent channel messages due to permissions."
        print("Warning: Bot lacks 'Read Message History' permission to backread.")
    except Exception as e:
        backread_messages_str = f"Error retrieving recent channel messages: {e}"
        print(f"Error during backread: {e}")
    
    return backread_messages_str


async def process_and_send_response(message, openai_response):
    if not openai_response:
        await message.reply("Sorry, I couldn't get a response from the API.")
        return
    
    emoji = get_string_between_reacts(openai_response)
    if "!react" in openai_response:
        
        cleaned_response = openai_response.replace("!react", "")
        if emoji:
            cleaned_response = cleaned_response.replace(emoji, "")
            try:
                await message.add_reaction(emoji)
            except discord.errors.HTTPException:
                print(f"Failed to add reaction: {emoji}")
        if cleaned_response.strip():
            await message.reply(cleaned_response)
    else:
        await message.reply(openai_response)


client.run(discord_token)
