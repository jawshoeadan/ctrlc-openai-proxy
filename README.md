# Ctrl+C OpenAI Proxy

A Python server mimicking the OpenAI API that lets you quickly copy requests and paste responses made to it. Useful for developing and debugging, and for copying + pasting responses from other sources, i.e. using a response from the ChatGPT web app inside RooCode.

I made this to use my Gemini subscription with other apps, and this program served as a middle man allowing me to use programs I was already familiar with, i.e. RooCode and copy and paste answers from the Gemini Web App. In the process, I got a great understanding of how MCPs work under the hood as well as how the OpenAI API works.

## Use Cases

1. **Development Testing**: Test OpenAI API integrations without making actual API calls
2. **Mock Responses**: Generate mock responses for development and testing
3. **Debugging**: Inspect and modify API requests and responses
4. **Copying + Pasting**: Point an AI app to this server and use it to copy and paste responses from other sources

## Setup

1. Install dependencies:

```bash
uv sync
```

2. Run the server:

```bash
uv run main.py
```

The server will start at `http://127.0.0.1:8000`

## Usage

1. Access the web interface at `http://127.0.0.1:8000`
2. Set your OpenAI base url to `http://127.0.0.1:8000` in whichever program you're using.
3. Submit a request in that app, go to the web interface, and copy the response from the web interface and paste it into the app.

### Note

A lot of apps will first send a request to verify that the API is working (Cursor does this, could be a little finnicky), so you have to send a response to that request for the app to work

Tested with RooCode and ChatWise
