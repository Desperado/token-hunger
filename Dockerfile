# costbench hosted demo (deploy Architecture "B": serve a pre-pulled, offline
# dataset — the box never touches a database).
#
# SAFETY: deploy KEYLESS (no ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
# in the environment) so the /api/run endpoint cannot spend credits. The bundled
# offline demo + model picker still work without keys.
#
# Required env on the host:
#   COSTBENCH_PUBLIC_HOST=<your-domain>   # e.g. costbench-xxxx.up.railway.app
#                                          # relaxes serve()'s loopback-only guard
#   PORT is provided by Railway.
FROM python:3.12-slim
WORKDIR /app
COPY . .
# Editable install keeps the bundled ui/ assets resolvable via the source tree.
# [models] pulls LiteLLM so `model` targets can actually run; [tokenizers] for
# better local cost estimation.
RUN pip install --no-cache-dir -e ".[models,tokenizers]"
ENV PORT=8765
CMD ["sh", "-c", "costbench serve --host 0.0.0.0 --port ${PORT:-8765} --no-open"]
