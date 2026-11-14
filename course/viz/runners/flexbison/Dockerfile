# code-viz runner "flexbison" (runners/flexbison/Dockerfile).
# flex, bison 3.8 and gcc with Python, for viz=bison: bisontrace.py builds the parser with tracing
# on and turns bison's trace into steps; also used for the grammars in viz/manifest.json.
#
# How it is used: code-viz builds this image as code-viz-flexbison:<hash of this file> the first time an
# example needs it (docker build --network host: downloads time out on minipc's default bridge),
# runs examples in throwaway containers with --network none (agents: the Ollama network only),
# --cpus 1, --memory 1g, --pids-limit 256, mounting the tracers read-only at /viz/tracers and the
# job folder at /work (tracers/driver.py), and removes the image afterwards unless --keep-images.
# Change the pinned versions here; the new hash makes code-viz rebuild.
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends flex bison gcc libc6-dev make libfl-dev graphviz && rm -rf /var/lib/apt/lists/*
WORKDIR /work
