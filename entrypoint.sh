#!/bin/sh

# Entry point for the python app.  If DEBUG_APP environment variable is truthy,
# start the program under debugpy and wait for an external debugger to attach.
# Otherwise just execute the provided command (or default to running main.py).

if [ "${DEBUG_APP}" = "1" ]; then
    echo "Starting in debug mode on port 5678"
    if [ "${DEBUG_WAIT_FOR_CLIENT}" = "1" ]; then
        echo "Waiting for debugger to attach..."
        exec python -m debugpy --listen 0.0.0.0:5678 --wait-for-client main.py
    else
        exec python -m debugpy --listen 0.0.0.0:5678 main.py
    fi
else
    # if a custom command is supplied, run it; otherwise run main.py
    if [ "$#" -gt 0 ]; then
        exec "$@"
    else
        exec python main.py
    fi
fi
