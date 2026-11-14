# code-viz runner "vhdl" (runners/vhdl/Dockerfile).
# Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 2 Architecture (Runners), 7 Kinds of visualization, 15 Where things run and safety.
# GHDL 5.0.1 (mcode backend) with Python 3.12.16, for VHDL examples: the testbench simulated, its signals read from the VCD file.
#
# How it is used: code-viz builds this image as code-viz-vhdl:<hash of this file> the first time an
# example needs it (docker build --network host: downloads time out on minipc's default bridge),
# runs examples in throwaway containers with --network none, --cpus 1, --memory 1g, --pids-limit 256,
# mounting the tracers read-only at /viz/tracers and the job folder at /work (tracers/driver.py and
# tracers/langrun.py), and removes the image afterwards unless --keep-images.
# Change the pinned versions here; the new hash makes code-viz rebuild. python3 is only the driver.
FROM python:3.12.16-slim-trixie
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends ghdl-mcode=5.0.1+dfsg-1+b1 ghdl=5.0.1+dfsg-1+b1 && rm -rf /var/lib/apt/lists/*
WORKDIR /work
