import discord
import requests
import yaml
import json
import time

# Load stuff from config.yaml
try:
    with open("config.yaml", "r") as f:
        keys = yaml.safe_load(f)
        openai_url = keys.get("openai_url")
        discord_token = keys.get("discord_token")
        temperature = keys.get("temperature", 0.7)
        context_size = keys.get("context_size", 2048)
        output_size = keys.get("output_size", 512)
        conversation_timeout = keys.get("conversation_timeout", 60)  # Default 60 seconds (1 minute)
        backread_message_count = keys.get("backread_message_count", 3) # Default backread 3 messages
        prompt = keys.get("system_prompt", " ")



    
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

# system prompt, Might move it to config.yaml for easier modification
system_prompt = prompt
# Debugging purposes
print("Url:", openai_url, "Discord Token:", discord_token, "Temperature:", temperature, "Context_Size:", context_size, "Output Size:", output_size, "Conversation Timeout:", conversation_timeout, "Backread amount:", backread_message_count)
    except Exception as e:
        print("An error occurred:", e)

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
client = discord.Client(intents=intents)


conversation_history = {} 


last_interaction_time = {}



async def ask_openai(user_id, prompt, backread_context=""):
    headers = {
        'Content-Type': 'application/json',
    }

    
    if user_id not in conversation_history:
        conversation_history[user_id] = [{"role": "system", "content": system_prompt}]

    current_history = conversation_history[user_id]


    if backread_context:
        current_history.append({"role": "system", "content": "Recent channel messages for context:\n" + backread_context})

    current_history.append({"role": "user", "content": prompt})


    data = {
        "messages": current_history, 
        "temperature": temperature,
        "max_tokens": output_size,
        # "context_window": context_size, #  Remove '#' if your API supports context window for chat completions
    }

    try:
        response = requests.post(openai_url, headers=headers, json=data)
        response.raise_for_status()
        response_json = response.json()

        if 'choices' in response_json and response_json['choices']:
            if 'message' in response_json['choices'][0] and 'content' in response_json['choices'][0]['message']:
                ai_response_text = response_json['choices'][0]['message']['content']
                conversation_history[user_id].append({"role": "assistant", "content": ai_response_text})
                return ai_response_text
            elif 'text' in response_json['choices'][0]: # For older openai API format
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
        return "the API returned an unexpected response."
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
    if user_id in last_interaction_time:
        if current_time - last_interaction_time[user_id] > conversation_timeout:
            if user_id in conversation_history:
                del conversation_history[user_id]
            await message.channel.send(f"<@{user_id}>, conversation timed out. Please ping me again to start a new conversation.")



    if client.user in message.mentions:
        user_prompt = message.content.replace(f'<@{client.user.id}>', '').strip()

        if not user_prompt and user_id in conversation_history and conversation_history[user_id] and len(conversation_history[user_id]) > 1:
            user_prompt = "continue the conversation"

        if not user_prompt:
            await message.reply("Yes? Please ask me something or start a conversation.")
            return

       
        backread_messages_str = ""
        try:
            async for past_message in channel.history(limit=backread_message_count + 1): 
                if past_message != message:
                    backread_messages_str = f"{past_message.author.name}: {past_message.content}\n" + backread_messages_str 
        except discord.errors.Forbidden:
            backread_messages_str = "Could not retrieve recent channel messages due to permissions."
            print("Warning: Bot lacks 'Read Message History' permission to backread.")
        except Exception as e:
            backread_messages_str = f"Error retrieving recent channel messages: {e}"
            print(f"Error during backread: {e}")


        async with message.channel.typing():
            openai_response = await ask_openai(user_id, user_prompt, backread_messages_str)
            if openai_response:
                await message.reply(openai_response)
            else:
                await message.reply("Sorry, I couldn't get a response from the API.")
        last_interaction_time[user_id] = current_time
    elif message.reference and message.reference.resolved and message.reference.resolved.author == client.user:
        user_prompt = message.content.strip()

        if not user_prompt:
            await message.reply("Please write a message to reply with.")
            return


        backread_messages_str = ""
        try:
            async for past_message in channel.history(limit=backread_message_count + 1):
                if past_message != message:
                    backread_messages_str = f"{past_message.author.name}: {past_message.content}\n" + backread_messages_str
        except discord.errors.Forbidden:
            backread_messages_str = "Could not retrieve recent channel messages due to permissions."
            print("Warning: Bot lacks 'Read Message History' permission to backread.")
        except Exception as e:
            backread_messages_str = f"Error retrieving recent channel messages: {e}"
            print(f"Error during backread: {e}")


        async with message.channel.typing():
            openai_response = await ask_openai(user_id, user_prompt, backread_messages_str) 
            if openai_response:
                await message.reply(openai_response)
            else:
                await message.reply("Sorry, I couldn't get a response from the API.")
        last_interaction_time[user_id] = current_time 
    elif user_id in last_interaction_time and current_time - last_interaction_time[user_id] <= conversation_timeout and user_id in conversation_history and conversation_history[user_id]:
        user_prompt = message.content.strip()

        if not user_prompt:
            return


        backread_messages_str = ""
        try:
            async for past_message in channel.history(limit=backread_message_count + 1):
                if past_message != message:
                    backread_messages_str = f"{past_message.author.name}: {past_message.content}\n" + backread_messages_str
        except discord.errors.Forbidden:
            backread_messages_str = "Could not retrieve recent channel messages due to permissions."
            print("Warning: Bot lacks 'Read Message History' permission to backread.")
        except Exception as e:
            backread_messages_str = f"Error retrieving recent channel messages: {e}"
            print(f"Error during backread: {e}")


        async with message.channel.typing():
            openai_response = await ask_openai(user_id, user_prompt, backread_messages_str)
            if openai_response:
                await message.reply(openai_response)
            else:
                await message.reply("Sorry, I couldn't get a response from the API.")
        last_interaction_time[user_id] = current_time


client.run(discord_token)
