from fastapi import FastAPI, Request, BackgroundTasks, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from uuid import uuid4
import asyncio, time, json, pyperclip, textwrap, html
from pathlib import Path

 # Ensure the 'static' directory exists so StaticFiles doesn't raise an error
Path("static").mkdir(exist_ok=True)
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)
app.mount("/static", StaticFiles(directory="static"), name="static")

# -----------------------------------------------------------------------------
# ──  In-memory store: {id: {"prompt": ..., "future": asyncio.Future}}
# -----------------------------------------------------------------------------
pending: dict[str, dict] = {}

KEEPALIVE_INTERVAL = 60       # seconds
REQUEST_TIMEOUT    = 1800    # 30 min – change as you like

# -----------------------------------------------------------------------------
# ──  OpenAI-compatible endpoint
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body   = await request.json()
    stream = body.get("stream", False)          # default OpenAI behaviour
    rid    = str(uuid4())

    # Check if this is a chat title request for ChatWise
    prompt_text = extract_prompt_text(body)
    # if "Generate a concise chat title" in prompt_text:
    #     print("Title skip")
        
    #     # Detect language from the prompt (currently just a placeholder)
    #     # In a real implementation, you might want to use a language detection library
    #     language = "en"  # Default to English
        
    #     response = {
    #         "id": f"chatcmpl-{rid}",
    #         "object": "chat.completion",
    #         "created": int(time.time()),
    #         "model": body.get("model", "gpt-3.5-turbo"),
    #         "choices": [{
    #             "index": 0,
    #             "message": {
    #                 "role": "assistant",
    #                 "content": json.dumps({
    #                     "language": language,
    #                     "title": "An interesting title!"
    #                 })
    #             },
    #             "finish_reason": "stop"
    #         }],
    #         "usage": {
    #             "prompt_tokens": len(prompt_text.split()),
    #             "completion_tokens": 1,
    #             "total_tokens": len(prompt_text.split()) + 1
    #         }
    #     }
    #     return JSONResponse(response)

    fut = asyncio.get_event_loop().create_future()
    pending[rid] = {"prompt": body, "future": fut, "t0": time.time()}

    # ---------- (A) ordinary, non-stream call --------------------------------
    
    if not stream:
        reply_json = await fut            # wait until you paste the answer
        return JSONResponse(reply_json)   # one-shot, no chunking

    # ---------- (B) stream=True: Server-Sent Events (SSE) ---------------------
    async def sse_stream():
        """
        Proper SSE stream:
          • While awaiting the operator's reply, emit an SSE *comment* every
            KEEPALIVE_INTERVAL seconds so proxies and the OpenAI client keep
            the socket open.
          • Once the reply arrives, emit one delta chunk followed by the
            terminating [DONE] sentinel, exactly like OpenAI’s API.
        """
        # Send an initial comment so the HTTP response starts immediately.
        yield b": connected\n\n"

        # Keep looping until the operator provides a reply.
        while not fut.done():
            try:
                # Wait for the reply, but only up to KEEPALIVE_INTERVAL.
                await asyncio.wait_for(fut, timeout=KEEPALIVE_INTERVAL)
            except asyncio.TimeoutError:
                # No reply yet → send a harmless SSE comment as a keep‑alive.
                yield b": keep-alive\n\n"

        # At this point the future is complete.
        reply_json = fut.result()
        assistant  = reply_json["choices"][0]["message"]["content"]

        # Final delta chunk
        delta = {
            "id": reply_json["id"],
            "object": "chat.completion.chunk",
            "created": reply_json["created"],
            "model": reply_json["model"],
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": assistant},
                "finish_reason": None
            }]
        }
        yield f"data: {json.dumps(delta)}\n\n".encode()

        # Terminate the stream exactly as OpenAI does
        yield b"data: [DONE]\n\n"

    return StreamingResponse(sse_stream(),
                             media_type="text/event-stream")

def extract_prompt_text(body: dict) -> str:
    """
    Return the concatenated `content` fields from any messages[]
    array in the OpenAI request.  Fallback to str(body) if not present.
    """
    if isinstance(body, dict) and "messages" in body:
        return "\n".join(
            m.get("content", "") for m in body["messages"] if isinstance(m, dict)
        )
    return str(body)
# -----------------------------------------------------------------------------
# ──  Web GUI
# -----------------------------------------------------------------------------
HTML_PAGE = """
<!doctype html><html><head>
  <title>Ctrl+C OpenAI Proxy</title>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <style>textarea{width:100%;height:6rem}</style>
</head><body class="container">
<h2>Pending API requests</h2>
<button id="refresh"
        hx-get="/requests"
        hx-target="#list"
        hx-swap="innerHTML">
  Refresh
</button>
<div id="list" hx-get="/requests"
     hx-trigger="load"
     hx-swap="innerHTML"></div>
</body></html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE

@app.get("/requests", response_class=HTMLResponse)
async def list_requests():
    rows = []
    for rid, entry in list(pending.items()):
        if entry["future"].done():           # skip finished
            continue
        prompt_text = html.escape(extract_prompt_text(entry["prompt"]))
        rows.append(f"""
<article>
  <header><strong>{rid}</strong></header>

  <!-- read-only view of the prompt text -->
  <textarea readonly style="width:100%;height:6rem">{prompt_text}</textarea>

  <!-- copies just the prompt text, not the whole JSON -->
  <button type="button" onclick="navigator.clipboard.writeText(this.previousElementSibling.value)">Copy&nbsp;Text</button>

  <!-- user pastes ONLY the assistant's text here -->
  <form hx-post="/reply/{rid}" hx-include="textarea">
    <textarea name="assistant" onkeydown="if((event.metaKey||event.ctrlKey)&&event.key==='Enter'){{event.preventDefault(); htmx.trigger(this.form, 'submit');}}" placeholder="Paste the model's answer here…" style="width:100%;height:6rem"></textarea>
    <button type="button" onclick="navigator.clipboard.readText().then(text => this.form.assistant.value = text)">Paste from Clipboard</button>
    <button type="submit">Send back (⌘ + Enter)</button>
  </form>
</article>
""")
    return "\n".join(rows) if rows else "<p>No pending calls.</p>"

@app.post("/reply/{rid}")
async def submit_reply(rid: str, assistant: str = Form(...)):
    """
    User pasted Claude/GPT output → build OpenAI-style envelope
    and complete the waiting future.
    """
    entry = pending.get(rid)
    if not entry:
        return JSONResponse({"error": "request not found"}, status_code=404)

    reply_json = {
        "id": f"manual-{rid}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "manual-relay",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": assistant},
            "finish_reason": "stop"
        }],
        "usage": {       # return zeros if you don’t want to estimate tokens
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }

    entry["future"].set_result(reply_json)
    return "✓ sent!"

# -----------------------------------------------------------------------------
# ──  Garbage collector – clean up abandoned requests
# -----------------------------------------------------------------------------
async def janitor():
    while True:
        now = time.time()
        for rid, e in list(pending.items()):
            if now - e["t0"] > REQUEST_TIMEOUT and not e["future"].done():
                e["future"].set_exception(
                    TimeoutError("user never provided a response"))
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(janitor())
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def catch_all(path: str):
    return JSONResponse({"message": "Route not found, but returning 200"}, status_code=200)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)