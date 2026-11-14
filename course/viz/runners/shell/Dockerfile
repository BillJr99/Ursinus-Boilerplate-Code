# code-viz runner "shell" (runners/shell/Dockerfile).
# bash and common tools with Python, for viz=cast: shellcast.py records each command and its output.
# Runs with no network, so downloading commands fail in the recording.
#
# How it is used: code-viz builds this image as code-viz-shell:<hash of this file> the first time an
# example needs it (docker build --network host: downloads time out on minipc's default bridge),
# runs examples in throwaway containers with --network none (agents: the Ollama network only),
# --cpus 1, --memory 1g, --pids-limit 256, mounting the tracers read-only at /viz/tracers and the
# job folder at /work (tracers/driver.py), and removes the image afterwards unless --keep-images.
# Change the pinned versions here; the new hash makes code-viz rebuild.
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends bash coreutils grep sed gawk jq && rm -rf /var/lib/apt/lists/*
WORKDIR /work
