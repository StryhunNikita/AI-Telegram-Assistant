AI Telegram Assistant

AI Telegram Assistant is a conversational Telegram bot built to simulate natural dialogue using the OpenAI API.
The bot a

The project is structured to be extendable, modular, and easy to maintain, with future support pl

Technologies

Python

aiogra

OpenAI API

AsyncIO

PostgreSQL database

(Plan

Features

Intelligent responses powered by a Large Language Model

Conversation context awareness: the bot remembers previous messages

Store recognition system using local JSON data without a database

Modular architecture with separate logic for bot interaction, memory handling, and LLM communication

Simple integration with .env for secure API key management

Fully asynchronous message handling for fast performance

Clear project structure for future upgrades and scaling

Store Lookup System (JSON-Based Recognition)

One of the key functional modules in this project is a store recognition system that works without a database.
Instead of storing brand and location data in SQL, the bot uses a structured JSON file that contains store names and city mappings.

How It Works

The user sends a message to the Telegram bot.

The bot stores the message in memory and analyzes it.

If the message requires AI processing, it is sent to the LLM with conversation history included.

If the message relates to store search, the bot reads the JSON file and attempts store/city matching.

The appropriate response is generated and returned to the user.

This creates a natural AI chat experience similar to ChatGPT — but inside Telegram, with additional structured logic and tools.