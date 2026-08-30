# Chat templates

`gemma-4.jinja` is the canonical Gemma 4 chat template, taken verbatim from

    https://huggingface.co/google/gemma-4-26B-A4B-it/resolve/main/chat_template.jinja
    sha256  ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4

`llama-template-analysis --template-file chat-templates/gemma-4.jinja` reports
`supports_tools`, `supports_tool_calls`, and `supports_parallel_tool_calls`.
Without a template that declares those, no tool is offered to the model and
`tool_choice: "required"` has nothing to bind to.

## When it is needed

Not for the GGUF we serve. `gemma-4-26B_q4_0-it.gguf` from
`google/gemma-4-26B-A4B-it-qat-q4_0-gguf` carries this exact template in its
`tokenizer.chat_template` metadata — byte-identical to the copy here, verified
by extracting it from the file's header — so `scripts/llama-server.sh` lets the
model's own template win and passes no `--chat-template-file`.

It is here for any llama.cpp-compatible GGUF that has no template of its own.
The active chat deployment uses the llama.cpp-built GGUF above, which carries
the template in its metadata.

`scripts/llama-server.sh` inspects the GGUF up front and falls back to this file
when the model has no template, or use `TEMPLATE=` to force one. The template is
a property of the Gemma 4 conversation format, not of a parameter count, so it
applies to any `gemma4` build.

A GGUF with a packed vision tower will not load into llama.cpp, but a template
can go missing from a compatible GGUF for other reasons.  The failure is
silent: the model loads, answers in prose, and never mentions that it was
offered no tools.

## Checking a GGUF

    uv run scripts/gguf_inspect.py <path-to.gguf>

Reads the header only, so it is instant on an 18 GB file.
