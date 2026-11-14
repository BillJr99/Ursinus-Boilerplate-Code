# code-viz runner "agents" (runners/agents/Dockerfile).
# Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 12 Recording agent examples, 15 Where things run and safety.
# Python with the HTTP clients the CS357 examples use, for viz=agent: agentrec.py records model calls
# and retrieval. The only runner given a network: --ollama-network NET, which must have a container
# named or aliased "ollama" (or OLLAMA_HOST set).
#
# How it is used: code-viz builds this image as code-viz-agents:<hash of this file> the first time an
# example needs it (docker build --network host: downloads time out on minipc's default bridge),
# runs examples in throwaway containers with --network none (agents: the Ollama network only),
# --cpus 1, --memory 1g, --pids-limit 256, mounting the tracers read-only at /viz/tracers and the
# job folder at /work (tracers/driver.py), and removes the image afterwards unless --keep-images.
# Change the pinned versions here; the new hash makes code-viz rebuild.
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/* \
 && npm install -g promptfoo@0.96.2 && pip install --no-cache-dir requests==2.32.3 httpx==0.27.2 numpy==2.1.3 ollama==0.4.4
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
