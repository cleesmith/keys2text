# Keys2Text Chat Application

Keys2Text Chat is your personal AI interaction platform that brings multiple language models together in a single, streamlined interface. This application enables both online and offline AI engagement, designed to serve users across all experience levels.


[![A quick look video of Keys2Text Chat](https://img.youtube.com/vi/h1bOAffFNHY/0.jpg)](https://youtube.com/live/h1bOAffFNHY?feature=share)


[sign in to Keys2Text Chat](https://keys2text-chat.onrender.com)


## Core Value Proposition

Keys2Text Chat transforms your AI interactions by providing a unified platform for accessing various AI providers. The application prioritizes your privacy, requires minimal setup, and maintains a clear focus on practical functionality. As an open-source solution, it offers complete transparency while eliminating subscription costs—you only pay for your direct API usage with chosen providers.

## Essential Features

The application delivers a comprehensive suite of capabilities designed to enhance your AI interaction:

**Provider Integration**
- Connect with industry-leading AI services including OpenAI, Google (Gemini), and Anthropic (Claude)
- Utilize offline capabilities through local providers such as Ollama and LM Studio
- Access specialized services like DuckDuckGo AI without API requirements

**User Experience**
- Get started immediately through Google authentication
- Configure provider access by entering your API keys in the settings interface
- Maintain your conversation history with robust export options
- Save important exchanges as snippets—defined as user-AI interaction pairs
- Customize AI response parameters to match your specific requirements

**Data Management**
- Export all content in plain text format for maximum compatibility
- Retain full control over your API keys and conversation data
- Exercise complete ownership of all your generated content

## Implementation Process

1. Access the hosted application through the provided link
2. Complete Google authentication process
3. Configure at least one API key in settings
4. Select your preferred AI provider and model
5. Begin your AI interactions

## Supported Providers

### Online Services (API Key Required)
- OpenAI (GPT-4 and o1)
- Google AI Studio (Gemini)
- Anthropic (Claude)
- Groq
- OpenRouter

### Online Services (No API Key Required)
- DuckDuckGo AI, but there are daily chat limits for the app and it's a single limit for all users

### Local Installation Required
- Ollama
- LM Studio

## Technical Highlights

Keys2Text Chat is built with your accessibility in mind, featuring an intuitive NiceGUI interface that welcomes users of all technical backgrounds. The platform supports continuous conversations across multiple AI models, adapting to various levels of model capability. All data management is handled through plain text, ensuring maximum compatibility and ease of use.

## Future Development

We actively encourage community participation through our GitHub repository, welcoming your feedback, bug reports, and feature proposals. An instructional video guide demonstrating Keys2Text Chat functionality is currently in development.

---

Experience streamlined AI interaction with Keys2Text Chat—where simplicity meets capability.

---

## Project Layout

```
tree -f -I 'build|dist' | sed 's|\./||g' | tr '\240' ' '                        
```

```
.
├── LICENSE
├── README.md
├── user_session_settings
│   ├── __init__.py
│   ├── user_session.py
│   └── user_settings.py
│
├── static
│   └── daemon.png
│
├── frontend.py
├── main.py
├── keys2text.py
├── requirements.txt
.
```
